"""Orchestrates the TDD cycle for each project: gates writes, runs tests, advances phases."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePath
from typing import Protocol

from tdd_mcp.cycle import (
    DONE,
    PHASE_GUIDANCE,
    FileKind,
    Outcome,
    Phase,
    after_coverage,
    after_write,
    may_write,
)
from tdd_mcp.languages.base import Function, LanguageAdapter, SuiteRun
from tdd_mcp.plan import Checklist, PlannedTest
from tdd_mcp.reports import SuiteCounts
from tdd_mcp.workspace import (
    Snapshot,
    WorkspaceError,
    replace_once,
    require_file,
    resolve_inside,
    restore,
    write_text,
)

OUTPUT_TAIL_CHARS = 6_000


class TddError(ValueError):
    """Raised when a request would break the TDD cycle or is otherwise invalid."""


class History(Protocol):
    def head_commit(self, root: Path) -> str: ...

    def is_ancestor(self, root: Path, commit: str) -> bool: ...

    def changed_lines(self, root: Path, base: str) -> dict[str, frozenset[int]]: ...

    def rollback(self, root: Path, commit: str) -> str: ...

    def set_aside(self, root: Path, paths: list[str]) -> None: ...


@dataclass(frozen=True)
class Report:
    phase: Phase
    message: str
    output: str = ""

    def render(self) -> str:
        text = f"Phase: {self.phase}\n{self.message}"
        if self.output:
            text += f"\n\n{self.output[-OUTPUT_TAIL_CHARS:]}"
        return text


@dataclass
class _Session:
    adapter: LanguageAdapter
    phase: Phase = Phase.COVERAGE_REQUIRED
    # Test count at the last coverage run: the baseline new tests are counted against.
    tests: int = 0
    # Commit the current cycle started from; its changes must all be covered by tests.
    base: str | None = None
    # Phase the uncommitted step began in; further edits amend that step.
    step: Phase | None = None
    last_failing: int = 0
    last_added: int = 0
    last_block: tuple[dict[str, frozenset[int]], ...] | None = None
    checklist: Checklist | None = None


class TddService:
    def __init__(
        self,
        adapters: Mapping[str, LanguageAdapter],
        *,
        pending_changes: Callable[[Path], list[str]],
        history: History | None = None,
        exempt: Sequence[str] = (),
        require_plan: bool = False,
    ) -> None:
        self.require_plan = require_plan
        self._adapters = adapters
        self._pending_changes = pending_changes
        self._history = history
        # fnmatch patterns on root-relative POSIX paths; `*` also matches `/`.
        self.exempt = tuple(exempt)
        self._sessions: dict[Path, _Session] = {}
        self._refused: tuple[str, ...] | None = None

    def status(self, location: str) -> Report:
        session = self._sessions.get(_root(location))
        phase = session.phase if session else Phase.COVERAGE_REQUIRED
        return Report(phase, PHASE_GUIDANCE[phase])

    def plan_tests(self, location: str, tests: Sequence[PlannedTest]) -> Report:
        session = self._started(_root(location))
        if session.phase is not Phase.PLAN:
            raise TddError(
                "plan_tests works only in the plan phase; you are in the "
                f"{session.phase} phase. {PHASE_GUIDANCE[session.phase]}"
            )
        session.checklist = Checklist(tests)
        session.phase = Phase.RED
        return Report(session.phase, session.checklist.reminder(session.phase))

    def advance_tdd_phase(self, location: str, language: str) -> Report:
        root = _root(location)
        adapter = self._adapter(language)
        session = self._sessions.get(root)
        fresh = session is None or session.adapter is not adapter
        if fresh:
            session = self._sessions[root] = _Session(adapter)

        run = adapter.run_coverage(root)
        session.step = None
        changed = self._cycle_changes(session, root, run)
        untested = self._untested_changes(session, changed, run)
        commented = self._commented_changes(session, root, changed)
        blocked = bool(untested or commented)
        failing = run.counts.failures if run.counts else 0
        restarts = fresh or run.outcome is Outcome.PASSED
        added = run.counts.tests - session.tests if run.counts and not restarts else 0
        session.phase = after_coverage(
            session.phase,
            run.outcome,
            untested_changes=blocked,
            failing=failing,
            added=added,
        )
        if self.require_plan and session.phase is Phase.RED:
            session.phase = Phase.PLAN
        session.last_failing, session.last_added = failing, added
        if run.counts and restarts:
            session.tests = run.counts.tests
        if session.phase is Phase.RED and restarts and not blocked and self._history:
            session.base = self._history.head_commit(root)
        message = f"Coverage run {run.outcome}."
        guidance = _guidance(session.phase, failing, added)
        repeated = blocked and session.last_block == (untested, commented)
        session.last_block = (untested, commented) if blocked else None
        if blocked:
            message = "Tests passed, but the next cycle is blocked."
            if repeated:
                message += (
                    " Nothing changed since your last advance_tdd_phase: the same "
                    "lines are still flagged. Fix them before advancing again."
                )
            guidance = (
                f"You are still in the {session.phase} phase; the next cycle "
                f"starts once these lines are fixed and committed. {DONE}"
            )
        if session.phase is Phase.RED and failing > 1:
            message += f" {failing} tests fail."
        if session.phase is Phase.RED and added > 1:
            message += f" {added} tests were added since the cycle started."
        if untested:
            message += (
                " Production lines changed this cycle aren't covered by any test: "
                f"{_untested_lines(adapter, root, untested, run.untaken)} In TDD every "
                "production line exists because a test needed it. This is a routine "
                "fix: simplify the code now with edit_file until only what your tests "
                "need remains (deleting those lines, or replacing a body with the "
                "simplest code that passes). Deleting this code is how you get to "
                "test it: tests can only be added in red, and red starts once the "
                "untested code is gone. The code quoted above is your copy: bring it "
                "back in green, one tested behaviour per cycle. Then commit ('. r'), "
                "call advance_tdd_phase again, and carry on with the task; don't stop "
                "or hand back to the user."
            )
        if commented:
            message += (
                " Lines changed this cycle hold comments: "
                f"{_listing(commented)}.{_quoted(root, commented)}"
                f"{_kept_code(adapter, root, commented)} Next: remove "
                "them, letting names say what the comments did, commit ('. r'), "
                "then call advance_tdd_phase again."
            )
        return Report(session.phase, f"{message} {guidance}", run.output)

    def run_coverage(self, location: str, language: str) -> Report:
        run = self._adapter(language).run_coverage(_root(location))
        return Report(
            self.status(location).phase,
            f"Coverage run {run.outcome} (phase unchanged). "
            "Only advance_tdd_phase moves the TDD cycle to its next phase.",
            run.output,
        )

    def _adapter(self, language: str) -> LanguageAdapter:
        adapter = self._adapters.get(language)
        if adapter is None:
            raise TddError(
                f"Unsupported language {language!r}. "
                f"Retry with language set to one of: {', '.join(self._adapters)}."
            )
        return adapter

    def return_to_red(self, location: str) -> Report:
        root = _root(location)
        session = self._started(root)
        if session.phase is not Phase.GREEN:
            raise TddError(
                "return_to_red works only from the green phase; you are in the "
                f"{session.phase} phase. {PHASE_GUIDANCE[session.phase]}"
            )
        changes = self._pending_changes(root)
        paths = [line[3:] for line in changes]
        history = self._history
        production = all(
            session.adapter.classify(PurePath(path)) is FileKind.PRODUCTION
            for path in paths
        )
        tests = [
            path
            for path in paths
            if session.adapter.classify(PurePath(path)) is FileKind.TEST
        ]
        if tests:
            raise TddError(
                f"The red step's test changes ({', '.join(tests)}) aren't committed "
                "yet, so the test is still editable: fix it with edit_file now, "
                "without return_to_red, then commit it as '. t'. You are in the "
                "green phase."
            )
        if changes and not (production and history):
            raise TddError(
                f"Uncommitted changes in {root}: "
                f"{', '.join(line.strip() for line in changes)}. Undo your green "
                "edits first (production files are still writable: edit them back), "
                "then call return_to_red again. You are in the green phase."
            )
        set_aside = ""
        if changes and history:
            history.set_aside(root, paths)
            set_aside = (
                f" Your uncommitted production changes ({', '.join(paths)}) were "
                "set aside in git stash ('tdd-mcp return_to_red'); write the "
                "production code again once the tests are fixed."
            )
        session.phase = Phase.RED
        return Report(
            session.phase,
            f"Back in the red phase.{set_aside} Tests are writable again and "
            "production code is locked. Next: edit the existing tests that assert "
            "the old behaviour "
            "so they pass without it (remove or loosen the obsolete assertions), "
            "or fix the new test if it's wrong (e.g. add a missing import); keep "
            "the new test failing for the behaviour it specifies. The first "
            "edit returns you to green, but you can keep editing tests until you "
            "commit them ('. t'). Then change production code.",
        )

    def rollback_cycle(self, location: str) -> Report:
        root = _root(location)
        session = self._started(root)
        base = session.base
        if (
            base is None
            or self._history is None
            or not self._history.is_ancestor(root, base)
        ):
            raise TddError(
                "No cycle start commit to roll back to (none recorded yet, or a git "
                f"reset moved past it). You are in the {session.phase} phase. Next: "
                "call advance_tdd_phase; it records one whenever every test passes."
            )
        backup = self._history.rollback(root, base)
        del self._sessions[root]
        report = self.advance_tdd_phase(location, session.adapter.name)
        return Report(
            report.phase,
            f"Rolled back to commit {base[:12]}, where this cycle started with "
            f"every test passing. The dropped commits are kept at {backup}; "
            f"uncommitted work, if any, is in git stash. {report.message}",
            report.output,
        )

    def write_file(self, location: str, path: str, content: str) -> Report:
        def write(target: Path) -> Snapshot:
            if target.is_file():
                session = self._sessions[_root(location)]
                adapter = session.adapter
                existing = target.read_text(encoding="utf-8", errors="replace")
                dropped = adapter.definitions(existing) - adapter.definitions(content)
                if dropped:
                    raise TddError(
                        "write_file replaces the whole file, and this content drops "
                        f"{', '.join(sorted(dropped))} from {path}. Use edit_file "
                        "to add, change or delete code, or include everything the "
                        "file should keep. Nothing was written. "
                        f"{PHASE_GUIDANCE[session.phase]}"
                    )
            return write_text(target, content)

        return self._refusing_repeats(
            ("write_file", location, path, content),
            lambda: self._apply(location, path, write),
        )

    def edit_file(
        self, location: str, path: str, old_string: str, new_string: str
    ) -> Report:
        def edit() -> Report:
            require_file(resolve_inside(_root(location), path))
            return self._apply(
                location,
                path,
                lambda target: replace_once(target, old_string, new_string),
            )

        return self._refusing_repeats(
            ("edit_file", location, path, old_string, new_string), edit
        )

    def _refusing_repeats(
        self, call: tuple[str, ...], attempt: Callable[[], Report]
    ) -> Report:
        try:
            return attempt()
        except TddError as refusal:
            if call == self._refused:
                raise TddError(
                    "This exact call was already refused, and retrying it "
                    f"unchanged is refused the same way. {refusal}"
                ) from refusal
            self._refused = call
            raise
        except WorkspaceError as error:
            session = self._sessions.get(Path(call[1]).resolve())
            phase = session.phase if session else Phase.COVERAGE_REQUIRED
            raise WorkspaceError(
                f"{error} Nothing was written. {PHASE_GUIDANCE[phase]}"
            ) from error

    def run_tests(
        self, location: str, path: str | None = None, test_name: str | None = None
    ) -> Report:
        root = _root(location)
        session = self._started(root)
        relative = None
        if path is not None:
            target = resolve_inside(root, path)
            if not target.exists():
                raise TddError(
                    f"Path {path!r} does not exist. Pass an existing test file or "
                    "folder relative to location, or omit path to run every test."
                )
            relative = target.relative_to(root).as_posix()
        for value in (relative, test_name):
            # The runner would parse it as an option (e.g. pytest's `-p` loads plugins).
            if value and value.startswith("-"):
                raise TddError(
                    f"Test selection {value!r} must not start with '-'. Pass a test "
                    "file, folder, or name without the leading '-'."
                )

        run = session.adapter.run_tests(root, relative, test_name)
        return Report(
            session.phase,
            f"Tests {run.outcome} (not a coverage run; phase unchanged).",
            run.output,
        )

    def _cycle_changes(
        self, session: _Session, root: Path, run: SuiteRun
    ) -> dict[str, frozenset[int]]:
        if (
            not self._history
            or session.base is None
            or run.outcome is not Outcome.PASSED
            or not self._history.is_ancestor(root, session.base)
        ):
            return {}
        return self._history.changed_lines(root, session.base)

    def _untested_changes(
        self, session: _Session, changed: dict[str, frozenset[int]], run: SuiteRun
    ) -> dict[str, frozenset[int]]:
        untested = {}
        for path, lines in changed.items():
            if session.adapter.classify(PurePath(path)) is not FileKind.PRODUCTION:
                continue
            missed = lines & run.uncovered.get(path, frozenset())
            if missed:
                untested[path] = missed
        return untested

    def _commented_changes(
        self, session: _Session, root: Path, changed: dict[str, frozenset[int]]
    ) -> dict[str, frozenset[int]]:
        commented = {}
        for path, lines in changed.items():
            if session.adapter.classify(PurePath(path)) is FileKind.OTHER:
                continue
            source = (root / path).read_text(encoding="utf-8", errors="replace")
            found = lines & session.adapter.comment_lines(source)
            if found:
                commented[path] = found
        return commented

    def _started(self, root: Path) -> _Session:
        session = self._sessions.get(root)
        if session is None:
            raise TddError(
                "No TDD cycle started for this location (you are in the "
                "coverage_required phase). Next: call advance_tdd_phase with this "
                "location, then retry."
            )
        return session

    def _apply(
        self, location: str, path: str, change: Callable[[Path], Snapshot]
    ) -> Report:
        root = _root(location)
        session = self._started(root)
        target = resolve_inside(root, path)
        relative = target.relative_to(root)
        exempt = any(fnmatch(relative.as_posix(), pattern) for pattern in self.exempt)
        kind = session.adapter.classify(relative)
        changes = self._pending_changes(root)
        guidance = _guidance(session.phase, session.last_failing, session.last_added)
        if not changes:
            session.step = session.phase
        elif session.step is None:
            if not exempt and not may_write(session.phase, kind):
                raise _locked(kind, session.phase, guidance, session.last_added)
            raise _uncommitted(root, changes, session.phase)
        phase = session.step

        if exempt:
            change(target)
            return Report(
                session.phase,
                f"Wrote {path} (exempt from the TDD cycle; tests not run).",
            )

        if not may_write(phase, kind):
            if changes and may_write(session.phase, kind):
                raise _uncommitted_step(root, changes, phase, session.phase)
            raise _locked(kind, phase, guidance, session.last_added)

        snapshot = change(target)
        if kind is FileKind.OTHER:
            return Report(session.phase, f"Wrote {path} (not code; tests not run).")

        run = session.adapter.run_tests(root)
        counts = run.counts or SuiteCounts(tests=session.tests, failures=0)
        added = counts.tests - session.tests
        passed = phase is Phase.GREEN and session.phase is Phase.REFACTOR
        transition = after_write(
            Phase.REFACTOR if passed else phase,
            kind,
            run.outcome,
            failing=counts.failures,
            added=added,
        )
        session.phase = transition.phase
        session.last_failing, session.last_added = counts.failures, added
        if session.phase is Phase.REFACTOR and not transition.revert:
            session.tests = counts.tests
        message = f"Tests {run.outcome}."
        if transition.reason:
            message += f" {transition.reason}"
        if transition.revert:
            restore(snapshot)
            message += f" {path} was reverted."
        if transition.revert and added > 0 and session.last_block:
            message += (
                " advance_tdd_phase is blocked right now, so first clear what it "
                "flagged (delete the untested code, remove the comments), commit, "
                "and advance; then add this test in red, one test per cycle."
            )
        undefined = _UNDEFINED_NAME.search(run.output)
        if kind is FileKind.TEST and session.phase is Phase.GREEN and undefined:
            name = undefined.group(1) or undefined.group(2)
            message += (
                f" The new test fails because {name} is not defined in it. "
                f"Production code can't fix that: the test must import {name}. "
                "Fix the test now; it stays editable until you commit it as '. t'."
            )
        refactoring = (
            phase is Phase.REFACTOR
            and kind is FileKind.PRODUCTION
            and not transition.revert
        )
        if refactoring or (phase is Phase.GREEN and session.phase is Phase.REFACTOR):
            coverage = session.adapter.run_coverage(root)
            changed = self._cycle_changes(session, root, coverage)
            untested = self._untested_changes(session, changed, coverage)
            lines = _untested_lines(session.adapter, root, untested, coverage.untaken)
            if untested and refactoring:
                message += (
                    " Refactoring can't add behaviour, and no test runs these "
                    f"production lines: {lines} New behaviour needs its own cycle: "
                    "take it out now with edit_file, commit, call advance_tdd_phase, "
                    "then write its failing test first."
                )
            elif untested:
                message += (
                    f" Your test doesn't run these production lines: {lines}"
                    " Simplify the code now with edit_file until only what your test "
                    "needs remains, often the simplest code that passes (e.g. "
                    "returning a constant); this green step stays open until you "
                    "commit it as '^ f'."
                )
        return Report(
            session.phase,
            f"{message} {_guidance(session.phase, counts.failures, added)}",
            "" if run.outcome is Outcome.PASSED else run.output,
        )


def _guidance(phase: Phase, failing: int, added: int) -> str:
    if phase is Phase.RED and (failing > 1 or added > 1):
        return (
            "You are in the red phase, which needs exactly one new test, failing. "
            "Production code is locked; tests are writable. Next: edit the test "
            "files until exactly one test fails: delete extra new tests entirely "
            "(a body of only `pass` still counts) or fix wrong ones. A test that "
            "fails only because it calls (or imports) code that doesn't exist yet is "
            "a valid failing test; nothing is wrong with the environment. If a test "
            "fails because production code is broken, don't delete it: call "
            "rollback_cycle to restart the cycle from its last passing commit."
        )
    return PHASE_GUIDANCE[phase]


def _listing(lines_by_path: dict[str, frozenset[int]]) -> str:
    return "; ".join(
        f"{path}: {', '.join(map(str, sorted(lines)))}"
        for path, lines in sorted(lines_by_path.items())
    )


def _quoted(root: Path, lines_by_path: dict[str, frozenset[int]]) -> str:
    quotes = []
    for path, lines in sorted(lines_by_path.items()):
        source = (root / path).read_text(encoding="utf-8", errors="replace")
        texts = source.splitlines()
        quotes += [
            f"{path}:{number}: {texts[number - 1]}"
            for number in sorted(lines)
            if number <= len(texts)
        ]
    return "".join(f"\n{quote}" for quote in quotes) + "\n"


def _untested_lines(
    adapter: LanguageAdapter,
    root: Path,
    untested: dict[str, frozenset[int]],
    untaken: Mapping[str, frozenset[int]],
) -> str:
    never_run = {
        path: lines - untaken.get(path, set()) for path, lines in untested.items()
    }
    dead = _dead_functions(adapter, root, never_run)
    loose = {
        path: frozenset(
            number
            for number in lines
            if not any(f.start <= number <= f.end for f in dead.get(path, ()))
        )
        for path, lines in untested.items()
    }
    unrun = {path: lines - untaken.get(path, set()) for path, lines in loose.items()}
    branches = {path: lines - unrun[path] for path, lines in loose.items()}
    return (
        f"{_listing(untested)}.{_quoted(root, unrun)}"
        f"{_branch_blocks(root, branches)}{_dead_blocks(root, dead)}"
    )


def _branch_blocks(root: Path, branches: dict[str, frozenset[int]]) -> str:
    if not any(branches.values()):
        return ""
    return (
        " These lines run, but one of their branches never does (e.g. an if whose "
        f"condition is never true in any test):{_quoted(root, branches)} Remove each "
        "such condition together with the code it guards, then simplify what's left "
        "(e.g. an emptied loop) so the test still passes."
    )


def _kept_code(
    adapter: LanguageAdapter, root: Path, commented: dict[str, frozenset[int]]
) -> str:
    kept = []
    for path, lines in sorted(commented.items()):
        source = (root / path).read_text(encoding="utf-8", errors="replace")
        code = adapter.uncommented(source)
        kept += [
            f"{path}:{number}: {code[number]}\n"
            for number in sorted(lines)
            if code.get(number, "").strip()
        ]
    if not kept:
        return ""
    return (
        " Keep the code on these lines and drop only the comment, so each line "
        "becomes:\n" + "".join(kept)
    )


def _dead_functions(
    adapter: LanguageAdapter, root: Path, untested: dict[str, frozenset[int]]
) -> dict[str, tuple[Function, ...]]:
    dead = {}
    for path, lines in sorted(untested.items()):
        source = (root / path).read_text(encoding="utf-8", errors="replace")
        found = tuple(f for f in adapter.functions(source) if f.body in lines)
        if found:
            dead[path] = found
    return dead


def _dead_blocks(root: Path, dead: dict[str, tuple[Function, ...]]) -> str:
    if not dead:
        return ""
    blocks = []
    for path, functions in dead.items():
        lines = (root / path).read_text(encoding="utf-8", errors="replace").splitlines()
        blocks += [
            f"{path} lines {f.start}-{f.end}:\n"
            + "".join(f"{line}\n" for line in lines[f.start - 1 : f.end])
            for f in functions
        ]
    return (
        " These functions never run, so delete each one whole, its first line "
        "included (edit_file with the quoted text as old_string and an empty "
        "new_string; if that leaves a class or block empty, delete it too):\n"
        + "".join(blocks)
    )


def _locked(kind: FileKind, phase: Phase, guidance: str, added: int = 0) -> TddError:
    if kind is FileKind.PRODUCTION and phase is Phase.RED and added > 1:
        guidance = (
            f"Production is locked because {added} new tests were added; red "
            f"needs exactly one. Next: delete {added - 1} of the new test "
            "functions from the test file entirely and keep one. If it fails "
            "because the production code doesn't exist yet (ModuleNotFoundError, "
            "ImportError, NameError, AttributeError), that's the failure you "
            "want: it moves you to green, where this write is allowed."
        )
    elif kind is FileKind.PRODUCTION and phase is Phase.RED:
        guidance += (
            " A test failing with ModuleNotFoundError, ImportError, NameError or "
            "AttributeError because the production code doesn't exist yet is the "
            "red failure you want; nothing is stuck. Don't define stand-ins for "
            "the production code in the test file: they make the test pass. "
            "Production files unlock in green, once exactly one test fails."
        )
    elif kind is FileKind.TEST and phase is Phase.GREEN:
        guidance += (
            " If the new test itself is wrong (e.g. it doesn't import what it "
            "uses), no production change can make it pass: call return_to_red and "
            "fix it there."
        )
    return TddError(
        f"Writing {kind} files is not allowed in the {phase} phase. {guidance}"
    )


def _uncommitted(root: Path, changes: list[str], phase: Phase) -> TddError:
    return TddError(
        f"Uncommitted changes in {root}: "
        f"{', '.join(line.strip() for line in changes)}. "
        "Commit them first (git add, then commit: '. t' for a new failing test, "
        "'^ f' for the code that passes it, '. r' for a refactoring), then retry "
        f"this edit. You are in the {phase} phase."
    )


_UNDEFINED_NAME = re.compile(
    r"NameError: name '(\w+)' is not defined|ReferenceError: (\w+) is not defined"
)

_STEP_COMMITS = {
    Phase.RED: ("'. t'", "test_only", "proven_safe"),
    Phase.GREEN: ("'^ f'", "feature", "validated"),
    Phase.REFACTOR: ("'. r'", "refactoring", "proven_safe"),
}


def _uncommitted_step(
    root: Path, changes: list[str], step: Phase, phase: Phase
) -> TddError:
    notation, intention, risk = _STEP_COMMITS[step]
    paths = json.dumps([line[3:] for line in changes])
    return TddError(
        f"Uncommitted changes in {root}: "
        f"{', '.join(line.strip() for line in changes)}. They are the {step} "
        f"step's changes: commit them as {notation} (racn intention {intention}, "
        f"risk {risk}, paths {paths}), then retry this edit. You are in the "
        f"{phase} phase."
    )


def _root(location: str) -> Path:
    root = Path(location).resolve()
    if not root.is_dir():
        raise TddError(
            f"Location does not exist or is not a directory: {location}. "
            "Pass the absolute path of the project root."
        )
    return root
