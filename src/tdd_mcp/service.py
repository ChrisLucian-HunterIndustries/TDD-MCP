"""Orchestrates the TDD cycle for each project: gates writes, runs tests, advances phases."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from tdd_mcp.cycle import (
    PHASE_GUIDANCE,
    FileKind,
    Phase,
    after_coverage,
    after_write,
    may_write,
)
from tdd_mcp.languages.base import LanguageAdapter
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


class TddService:
    def __init__(
        self,
        adapters: Mapping[str, LanguageAdapter],
        *,
        pending_changes: Callable[[Path], list[str]],
        exempt: Sequence[str] = (),
    ) -> None:
        self._adapters = adapters
        self._pending_changes = pending_changes
        # fnmatch patterns on root-relative POSIX paths; `*` also matches `/`.
        self.exempt = tuple(exempt)
        self._sessions: dict[Path, _Session] = {}

    def status(self, location: str) -> Report:
        session = self._sessions.get(_root(location))
        phase = session.phase if session else Phase.COVERAGE_REQUIRED
        return Report(phase, PHASE_GUIDANCE[phase])

    def run_coverage(self, location: str, language: str) -> Report:
        root = _root(location)
        adapter = self._adapters.get(language)
        if adapter is None:
            raise TddError(
                f"Unsupported language {language!r}. Supported: {', '.join(self._adapters)}"
            )
        session = self._sessions.get(root)
        if session is None or session.adapter is not adapter:
            session = self._sessions[root] = _Session(adapter)

        run = adapter.run_coverage(root)
        session.phase = after_coverage(session.phase, run.outcome)
        if run.counts:
            session.tests = run.counts.tests
        return Report(
            session.phase,
            f"Coverage run {run.outcome}. {PHASE_GUIDANCE[session.phase]}",
            run.output,
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
                raise TddError(f"Path {path!r} does not exist")
            relative = target.relative_to(root).as_posix()
        for value in (relative, test_name):
            # The runner would parse it as an option (e.g. pytest's `-p` loads plugins).
            if value and value.startswith("-"):
                raise TddError(f"Test selection {value!r} must not start with '-'")

        run = session.adapter.run_tests(root, relative, test_name)
        return Report(
            session.phase,
            f"Tests {run.outcome} (not a coverage run; phase unchanged).",
            run.output,
        )

    def _started(self, root: Path) -> _Session:
        session = self._sessions.get(root)
        if session is None:
            raise TddError(
                "No TDD cycle started for this location. Call run_coverage first."
            )
        return session

    def _apply(
        self, location: str, path: str, change: Callable[[Path], Snapshot]
    ) -> Report:
        root = _root(location)
        session = self._started(root)
        changes = self._pending_changes(root)
        if changes:
            raise TddError(
                f"Uncommitted changes in {root}: "
                f"{', '.join(line.strip() for line in changes)}. "
                "Commit them before the next edit, e.g. '. t' for a new failing "
                "test, then '^ f' for the code that passes it."
            )

        target = resolve_inside(root, path)
        relative = target.relative_to(root)
        if any(fnmatch(relative.as_posix(), pattern) for pattern in self.exempt):
            change(target)
            return Report(
                session.phase,
                f"Wrote {path} (exempt from the TDD cycle; tests not run).",
            )

        kind = session.adapter.classify(relative)
        if not may_write(session.phase, kind):
            raise TddError(
                f"Writing {kind} files is not allowed in the {session.phase} phase. "
                f"{PHASE_GUIDANCE[session.phase]}"
            )

        snapshot = change(target)
        if kind is FileKind.OTHER:
            return Report(session.phase, f"Wrote {path} (not code; tests not run).")

        run = session.adapter.run_tests(root)
        counts = run.counts or SuiteCounts(tests=session.tests, failures=0)
        transition = after_write(
            session.phase,
            kind,
            run.outcome,
            failing=counts.failures,
            added=counts.tests - session.tests,
        )
        session.phase = transition.phase
        message = f"Tests {run.outcome}."
        if transition.reason:
            message += f" {transition.reason}"
        if transition.revert:
            restore(snapshot)
            message += f" Refactoring must keep tests passing, so {path} was reverted."
        return Report(
            session.phase, f"{message} {PHASE_GUIDANCE[session.phase]}", run.output
        )


def _root(location: str) -> Path:
    root = Path(location).resolve()
    if not root.is_dir():
        raise TddError(f"Location does not exist or is not a directory: {location}")
    return root
