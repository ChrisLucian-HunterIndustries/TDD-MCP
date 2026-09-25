"""Orchestrates the TDD cycle for each project: gates writes, runs tests, advances phases."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
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


class TddService:
    def __init__(self, adapters: Mapping[str, LanguageAdapter]) -> None:
        self._adapters = adapters
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

    def _apply(
        self, location: str, path: str, change: Callable[[Path], Snapshot]
    ) -> Report:
        root = _root(location)
        session = self._sessions.get(root)
        if session is None:
            raise TddError(
                "No TDD cycle started for this location. Call run_coverage first."
            )

        target = resolve_inside(root, path)
        kind = session.adapter.classify(target.relative_to(root))
        if not may_write(session.phase, kind):
            raise TddError(
                f"Writing {kind} files is not allowed in the {session.phase} phase. "
                f"{PHASE_GUIDANCE[session.phase]}"
            )

        snapshot = change(target)
        if kind is FileKind.OTHER:
            return Report(session.phase, f"Wrote {path} (not code; tests not run).")

        run = session.adapter.run_tests(root)
        transition = after_write(session.phase, kind, run.outcome)
        session.phase = transition.phase
        message = f"Tests {run.outcome}."
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
