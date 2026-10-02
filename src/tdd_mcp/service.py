"""Orchestrates the TDD cycle for each project: gates writes, runs tests, advances phases."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePath
from typing import Protocol

from tdd_mcp.cycle import (
    PHASE_GUIDANCE,
    FileKind,
    Outcome,
    Phase,
    after_coverage,
    after_write,
    may_write,
)
from tdd_mcp.languages.base import LanguageAdapter, SuiteRun
from tdd_mcp.reports import SuiteCounts
from tdd_mcp.workspace import (
    Snapshot,
    replace_once,
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


class TddService:
    def __init__(
        self,
        adapters: Mapping[str, LanguageAdapter],
        *,
        pending_changes: Callable[[Path], list[str]],
        history: History | None = None,
        exempt: Sequence[str] = (),
    ) -> None:
        self._adapters = adapters
        self._pending_changes = pending_changes
        self._history = history
        # fnmatch patterns on root-relative POSIX paths; `*` also matches `/`.
        self.exempt = tuple(exempt)
        self._sessions: dict[Path, _Session] = {}

    def status(self, location: str) -> Report:
        session = self._sessions.get(_root(location))
        phase = session.phase if session else Phase.COVERAGE_REQUIRED
        return Report(phase, PHASE_GUIDANCE[phase])

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
        failing = run.counts.failures if run.counts else 0
        restarts = fresh or run.outcome is Outcome.PASSED
        added = run.counts.tests - session.tests if run.counts and not restarts else 0
        session.phase = after_coverage(
            session.phase,
            run.outcome,
            untested_changes=bool(untested or commented),
            failing=failing,
            added=added,
        )
        if run.counts and restarts:
            session.tests = run.counts.tests
        if session.phase is Phase.RED and restarts and self._history:
            session.base = self._history.head_commit(root)
        message = f"Coverage run {run.outcome}."
        guidance = _guidance(session.phase, failing, added)
        if untested or commented:
            message = "Tests passed, but the next cycle is blocked."
            guidance = (
                f"You are still in the {session.phase} phase; the next cycle "
                "starts once these lines are fixed and committed."
            )
        if session.phase is Phase.RED and failing > 1:
            message += f" {failing} tests fail."
        if session.phase is Phase.RED and added > 1:
            message += f" {added} tests were added since the cycle started."
        if untested:
            message += (
                " Production lines changed this cycle aren't covered by any test: "
                f"{_listing(untested)}. In TDD every production line exists because "
                "a test needed it, so this isn't normal progress. Next: delete those "
                "lines (adding tests for them now is reverted; bring the behaviour "
                "back later, one failing test per cycle), commit ('. r'), then call "
                "advance_tdd_phase again."
            )
        if commented:
            message += (
                " Lines changed this cycle hold comments: "
                f"{_listing(commented)}. Next: remove them, letting names say what "
                "the comments did, commit ('. r'), then call advance_tdd_phase again."
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
        if changes := self._pending_changes(root):
            raise TddError(
                f"Uncommitted changes in {root}: "
                f"{', '.join(line.strip() for line in changes)}. Undo your green "
                "edits first (production files are still writable: edit them back), "
                "then call return_to_red again. You are in the green phase."
            )
        session.phase = Phase.RED
        return Report(
            session.phase,
            "Back in the red phase; tests are writable again and production code "
            "is locked. Next: edit the existing tests that assert the old behaviour "
            "so they pass without it (remove or loosen the obsolete assertions); "
            "your new failing test already specifies the new behaviour. The first "
            "edit returns you to green, but you can keep editing tests until you "
            "commit them ('. t'). Then change production code.",
        )

    def rollback_cycle(self, location: str) -> Report:
        root = _root(location)
        session = self._started(root)
        base = session.base
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
        return self._apply(location, path, lambda target: write_text(target, content))

    def edit_file(
        self, location: str, path: str, old_string: str, new_string: str
    ) -> Report:
        return self._apply(
            location, path, lambda target: replace_once(target, old_string, new_string)
        )

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
        if not changes:
            session.step = session.phase
        elif session.step is None:
            if not exempt and not may_write(session.phase, kind):
                raise _locked(kind, session.phase)
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
                raise _uncommitted(root, changes, session.phase)
            raise _locked(kind, phase)

        snapshot = change(target)
        if kind is FileKind.OTHER:
            return Report(session.phase, f"Wrote {path} (not code; tests not run).")

        run = session.adapter.run_tests(root)
        counts = run.counts or SuiteCounts(tests=session.tests, failures=0)
        added = counts.tests - session.tests
        transition = after_write(
            phase,
            kind,
            run.outcome,
            failing=counts.failures,
            added=added,
        )
        session.phase = transition.phase
        if session.phase is Phase.REFACTOR and not transition.revert:
            session.tests = counts.tests
        message = f"Tests {run.outcome}."
        if transition.reason:
            message += f" {transition.reason}"
        if transition.revert:
            restore(snapshot)
            message += f" {path} was reverted."
        return Report(
            session.phase,
            f"{message} {_guidance(session.phase, counts.failures, added)}",
            run.output,
        )


def _guidance(phase: Phase, failing: int, added: int) -> str:
    if phase is Phase.RED and (failing > 1 or added > 1):
        return (
            "You are in the red phase, which needs exactly one new test, failing. "
            "Production code is locked; tests are writable. Next: edit the test "
            "files until exactly one test fails: delete extra new tests entirely "
            "(a body of only `pass` still counts) or fix wrong ones. If a test "
            "fails because production code is broken, stop and ask the user "
            "instead of deleting it."
        )
    return PHASE_GUIDANCE[phase]


def _listing(lines_by_path: dict[str, frozenset[int]]) -> str:
    return "; ".join(
        f"{path}: {', '.join(map(str, sorted(lines)))}"
        for path, lines in sorted(lines_by_path.items())
    )


def _locked(kind: FileKind, phase: Phase) -> TddError:
    return TddError(
        f"Writing {kind} files is not allowed in the {phase} phase. "
        f"{PHASE_GUIDANCE[phase]}"
    )


def _uncommitted(root: Path, changes: list[str], phase: Phase) -> TddError:
    return TddError(
        f"Uncommitted changes in {root}: "
        f"{', '.join(line.strip() for line in changes)}. "
        "Commit them first (git add, then commit: '. t' for a new failing test, "
        "'^ f' for the code that passes it, '. r' for a refactoring), then retry "
        f"this edit. You are in the {phase} phase."
    )


def _root(location: str) -> Path:
    root = Path(location).resolve()
    if not root.is_dir():
        raise TddError(
            f"Location does not exist or is not a directory: {location}. "
            "Pass the absolute path of the project root."
        )
    return root
