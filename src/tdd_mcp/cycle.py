"""The red/green/refactor state machine, independent of any language or file system."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Phase(StrEnum):
    COVERAGE_REQUIRED = "coverage_required"
    PLAN = "plan"
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


DONE = (
    "The task is done only when advance_tdd_phase moves on with nothing flagged "
    "and every behaviour has its own test; don't report it done before then."
)

PHASE_GUIDANCE: dict[Phase, str] = {
    Phase.COVERAGE_REQUIRED: (
        "You are in the coverage_required phase. Code files are locked; retrying "
        "write_file or edit_file won't help. Next: call advance_tdd_phase. If it "
        "can't run the tests (e.g. pytest-cov or vitest is missing), stop and ask "
        "the user to fix that. To move on: advance_tdd_phase runs the tests; all "
        "passing starts red."
    ),
    Phase.PLAN: (
        "You are in the plan phase. Code files are locked. Next: call plan_tests "
        "with every test the task needs, and no more, each with a name, arrange, "
        "act and assert."
    ),
    Phase.RED: (
        "You are in the red phase. Production code is locked. Next: write exactly "
        "ONE new test that fails, for the smallest untested behaviour (one winning "
        "row, not every way to win). A test that imports code that doesn't exist "
        "yet counts as failing. To move on to green: exactly one new test fails; "
        "commit it as '. t'. Keep cycling until every behaviour has its own test."
    ),
    Phase.GREEN: (
        "You are in the green phase. Tests are locked. Next: change production "
        "code until every test passes, writing the simplest code that does what "
        "the test asserts, even if it looks too simple. To move on to refactor: "
        "every test passes; commit it as '^ f'. If an older test asserts the old "
        "behaviour, or the new test can't pass whatever the code does (e.g. a "
        "missing import), call return_to_red."
    ),
    Phase.REFACTOR: (
        "You are in the refactor phase. Tests and production code are writable; "
        "an edit that breaks a test or adds one is reverted. Next: optionally "
        "tidy, commit ('. r') if git shows changes, then call advance_tdd_phase. "
        "It starts the next cycle once every test passes, every production line "
        "changed this cycle runs in a test, those lines hold no comments, and "
        "everything is committed. " + DONE
    ),
}

_WRITABLE: dict[Phase, frozenset[FileKind]] = {
    Phase.COVERAGE_REQUIRED: frozenset({FileKind.OTHER}),
    Phase.PLAN: frozenset({FileKind.OTHER}),
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
    added: int = 0,
) -> Phase:
    if outcome is Outcome.PASSED:
        return phase if untested_changes else Phase.RED
    if phase is Phase.GREEN:
        return Phase.GREEN
    if outcome is Outcome.FAILED and (failing > 1 or added > 1):
        return Phase.RED
    if outcome is Outcome.FAILED and failing == 1:
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
                reason=(
                    f"{added} tests were added since the cycle started, but red "
                    "allows only one, and production code stays locked until then. "
                    f"Next: edit the test file and delete {added - 1} of the new "
                    "test functions entirely (a test whose body is only `pass` "
                    "still counts)."
                ),
            )
        if outcome is Outcome.FAILED and failing > 1:
            return Transition(
                Phase.RED,
                reason=(
                    f"{failing} tests fail; exactly one failing test may drive the "
                    "next change. Make the others pass or remove them."
                ),
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
        if outcome is Outcome.PASSED:
            return Transition(
                Phase.RED,
                reason=(
                    "Every test passes, so you are still in red. Make the new test "
                    "check behaviour that doesn't exist yet, and name its file and "
                    "function the way the test runner finds them."
                ),
            )
        return Transition(Phase.GREEN)
    if phase is Phase.GREEN:
        if outcome is Outcome.PASSED:
            return Transition(Phase.REFACTOR)
        return Transition(
            Phase.GREEN,
            reason=(
                "Tests still fail: keep changing production code until all pass. "
                "If other existing tests now fail because they assert the old "
                "behaviour, undo your production edits and call return_to_red to "
                "update those tests first."
            ),
        )
    if added > 0:
        return Transition(
            Phase.REFACTOR,
            revert=True,
            reason=(
                f"Refactoring must not add tests ({added} added); new behaviour "
                "needs its own red phase: call advance_tdd_phase, then add the test."
            ),
        )
    return Transition(
        Phase.REFACTOR,
        revert=outcome is not Outcome.PASSED,
        reason=""
        if outcome is Outcome.PASSED
        else (
            "Refactoring must keep tests passing. Make a smaller change, or call "
            "advance_tdd_phase to start a new cycle."
        ),
    )
