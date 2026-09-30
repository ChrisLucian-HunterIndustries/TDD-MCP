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
        if session is None or session.adapter is not adapter:
            session = self._sessions[root] = _Session(adapter)

        run = adapter.run_coverage(root)
        session.step = None
        untested = self._untested_changes(session, root, run)
        session.phase = after_coverage(
            session.phase,
            run.outcome,
            untested_changes=bool(untested),
            failing=run.counts.failures if run.counts else 0,
        )
        if run.counts:
            session.tests = run.counts.tests
        if session.phase is Phase.RED and self._history:
            session.base = self._history.head_commit(root)
        message = f"Coverage run {run.outcome}."
        if untested:
            listed = "; ".join(
                f"{path}: {', '.join(map(str, sorted(lines)))}"
                for path, lines in sorted(untested.items())
            )
            message += (
                " Production lines changed this cycle aren't covered by any test: "
                f"{listed}. Delete code no test requires (still in refactor), commit, "
                "then call advance_tdd_phase again; the next cycle can't start "
                "until every changed line is covered."
            )
        return Report(
            session.phase, f"{message} {PHASE_GUIDANCE[session.phase]}", run.output
        )

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
        session = self._started(_root(location))
        if session.phase is not Phase.GREEN:
            raise TddError(
                "return_to_red works only from the green phase; you are in the "
                f"{session.phase} phase. {PHASE_GUIDANCE[session.phase]}"
            )
        session.phase = Phase.RED
        return Report(session.phase, PHASE_GUIDANCE[session.phase])

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

    def _untested_changes(
        self, session: _Session, root: Path, run: SuiteRun
    ) -> dict[str, frozenset[int]]:
        if (
            not self._history
            or session.base is None
            or run.outcome is not Outcome.PASSED
            or not self._history.is_ancestor(root, session.base)
        ):
            return {}
        untested = {}
        for path, lines in self._history.changed_lines(root, session.base).items():
            if session.adapter.classify(PurePath(path)) is not FileKind.PRODUCTION:
                continue
            missed = lines & run.uncovered.get(path, frozenset())
            if missed:
                untested[path] = missed
        return untested

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
        changes = self._pending_changes(root)
        if not changes:
            session.step = session.phase
        elif session.step is None:
            raise _uncommitted(root, changes, session.phase)
        phase = session.step

        target = resolve_inside(root, path)
        relative = target.relative_to(root)
        if any(fnmatch(relative.as_posix(), pattern) for pattern in self.exempt):
            change(target)
            return Report(
                session.phase,
                f"Wrote {path} (exempt from the TDD cycle; tests not run).",
            )

        kind = session.adapter.classify(relative)
        if not may_write(phase, kind):
            if changes and may_write(session.phase, kind):
                raise _uncommitted(root, changes, session.phase)
            raise TddError(
                f"Writing {kind} files is not allowed in the {phase} phase. "
                f"{PHASE_GUIDANCE[phase]}"
            )

        snapshot = change(target)
        if kind is FileKind.OTHER:
            return Report(session.phase, f"Wrote {path} (not code; tests not run).")

        run = session.adapter.run_tests(root)
        counts = run.counts or SuiteCounts(tests=session.tests, failures=0)
        transition = after_write(
            phase,
            kind,
            run.outcome,
            failing=counts.failures,
            added=counts.tests - session.tests,
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
            session.phase, f"{message} {PHASE_GUIDANCE[session.phase]}", run.output
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
