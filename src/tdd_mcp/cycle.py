"""The red/green/refactor state machine, independent of any language or file system."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Phase(StrEnum):
    COVERAGE_REQUIRED = "coverage_required"
    RED = "red"
    GREEN = "green"
    REFACTOR = "refactor"


class FileKind(StrEnum):
    TEST = "test"
    PRODUCTION = "production"
    OTHER = "other"


class Outcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


PHASE_GUIDANCE: dict[Phase, str] = {
    Phase.COVERAGE_REQUIRED: "Run coverage; all tests must pass before writing a new test.",
    Phase.RED: "Write a test that fails. Production code is locked.",
    Phase.GREEN: "Write production code to make the failing test pass. Tests are locked.",
    Phase.REFACTOR: (
        "Refactor test or production code; edits that break tests are reverted. "
        "Run coverage to start the next cycle."
    ),
}

_WRITABLE: dict[Phase, frozenset[FileKind]] = {
    Phase.COVERAGE_REQUIRED: frozenset({FileKind.OTHER}),
    Phase.RED: frozenset({FileKind.OTHER, FileKind.TEST}),
    Phase.GREEN: frozenset({FileKind.OTHER, FileKind.PRODUCTION}),
    Phase.REFACTOR: frozenset(FileKind),
}


@dataclass(frozen=True)
class Transition:
    phase: Phase
    revert: bool = False


def may_write(phase: Phase, kind: FileKind) -> bool:
    return kind in _WRITABLE[phase]


def after_coverage(phase: Phase, outcome: Outcome) -> Phase:
    if outcome is Outcome.PASSED:
        return Phase.RED
    if phase is Phase.GREEN:
        return Phase.GREEN
    return Phase.COVERAGE_REQUIRED


def after_write(phase: Phase, kind: FileKind, outcome: Outcome) -> Transition:
    """The phase that follows writing a code file of `kind` and running the tests."""
    if kind is FileKind.OTHER:
        raise ValueError("Transitions apply to only code files")
    if not may_write(phase, kind):
        raise ValueError(f"Writing {kind} files is not allowed in the {phase} phase")
    if phase is Phase.RED:
        return Transition(Phase.GREEN if outcome is Outcome.FAILED else Phase.RED)
    if phase is Phase.GREEN:
        return Transition(Phase.REFACTOR if outcome is Outcome.PASSED else Phase.GREEN)
    return Transition(Phase.REFACTOR, revert=outcome is not Outcome.PASSED)
