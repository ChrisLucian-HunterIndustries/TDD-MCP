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
    reason: str = ""


def may_write(phase: Phase, kind: FileKind) -> bool:
    return kind in _WRITABLE[phase]


def after_coverage(
    phase: Phase,
    outcome: Outcome,
    *,
    untested_changes: bool = False,
    failing: int = 0,
) -> Phase:
    if outcome is Outcome.PASSED:
        return phase if untested_changes else Phase.RED
    if phase is Phase.GREEN or (outcome is Outcome.FAILED and failing == 1):
        return Phase.GREEN
    return Phase.COVERAGE_REQUIRED


def after_write(
    phase: Phase,
    kind: FileKind,
    outcome: Outcome,
    *,
    failing: int = 1,
    added: int = 0,
) -> Transition:
    """The phase that follows writing a code file of `kind` and running the tests."""
    if kind is FileKind.OTHER:
        raise ValueError("Transitions apply to only code files")
    if not may_write(phase, kind):
        raise ValueError(f"Writing {kind} files is not allowed in the {phase} phase")
    if phase is Phase.RED:
        if added > 1:
            return Transition(
                Phase.RED,
                reason=f"{added} tests were added since the last coverage run; add exactly one.",
            )
        if outcome is Outcome.FAILED and failing > 1:
            return Transition(
                Phase.RED,
                reason=f"{failing} tests fail; exactly one failing test may drive the next change.",
            )
        if outcome is Outcome.ERROR:
            return Transition(
                Phase.GREEN,
                reason=(
                    "The tests couldn't be collected or run, which counts as your "
                    "failing test. Check the output shows it fails for the intended "
                    "reason (e.g. code that doesn't exist yet)."
                ),
            )
        return Transition(Phase.GREEN if outcome is Outcome.FAILED else Phase.RED)
    if phase is Phase.GREEN:
        return Transition(Phase.REFACTOR if outcome is Outcome.PASSED else Phase.GREEN)
    if added > 0:
        return Transition(
            Phase.REFACTOR,
            revert=True,
            reason=f"Refactoring must not add tests ({added} added); new behaviour needs its own red phase.",
        )
    return Transition(
        Phase.REFACTOR,
        revert=outcome is not Outcome.PASSED,
        reason=""
        if outcome is Outcome.PASSED
        else "Refactoring must keep tests passing.",
    )
