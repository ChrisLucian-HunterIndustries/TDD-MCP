import pytest

from tdd_mcp.cycle import (
    FileKind,
    Outcome,
    Phase,
    after_coverage,
    after_write,
    may_write,
)


@pytest.mark.parametrize(
    ("phase", "kind", "allowed"),
    [
        (Phase.COVERAGE_REQUIRED, FileKind.TEST, False),
        (Phase.COVERAGE_REQUIRED, FileKind.PRODUCTION, False),
        (Phase.COVERAGE_REQUIRED, FileKind.OTHER, True),
        (Phase.RED, FileKind.TEST, True),
        (Phase.RED, FileKind.PRODUCTION, False),
        (Phase.RED, FileKind.OTHER, True),
        (Phase.GREEN, FileKind.TEST, False),
        (Phase.GREEN, FileKind.PRODUCTION, True),
        (Phase.GREEN, FileKind.OTHER, True),
        (Phase.REFACTOR, FileKind.TEST, True),
        (Phase.REFACTOR, FileKind.PRODUCTION, True),
        (Phase.REFACTOR, FileKind.OTHER, True),
    ],
)
def test_may_write(phase, kind, allowed):
    assert may_write(phase, kind) is allowed


@pytest.mark.parametrize(
    ("phase", "outcome", "expected"),
    [
        (Phase.COVERAGE_REQUIRED, Outcome.PASSED, Phase.RED),
        (Phase.COVERAGE_REQUIRED, Outcome.FAILED, Phase.COVERAGE_REQUIRED),
        (Phase.COVERAGE_REQUIRED, Outcome.ERROR, Phase.COVERAGE_REQUIRED),
        (Phase.RED, Outcome.PASSED, Phase.RED),
        (Phase.RED, Outcome.FAILED, Phase.COVERAGE_REQUIRED),
        (Phase.GREEN, Outcome.PASSED, Phase.RED),
        (Phase.GREEN, Outcome.FAILED, Phase.GREEN),
        (Phase.GREEN, Outcome.ERROR, Phase.GREEN),
        (Phase.REFACTOR, Outcome.PASSED, Phase.RED),
        (Phase.REFACTOR, Outcome.FAILED, Phase.COVERAGE_REQUIRED),
    ],
)
def test_after_coverage(phase, outcome, expected):
    assert after_coverage(phase, outcome) is expected


@pytest.mark.parametrize(
    ("phase", "kind", "outcome", "expected_phase", "revert"),
    [
        (Phase.RED, FileKind.TEST, Outcome.FAILED, Phase.GREEN, False),
        (Phase.RED, FileKind.TEST, Outcome.PASSED, Phase.RED, False),
        (Phase.RED, FileKind.TEST, Outcome.ERROR, Phase.RED, False),
        (Phase.GREEN, FileKind.PRODUCTION, Outcome.PASSED, Phase.REFACTOR, False),
        (Phase.GREEN, FileKind.PRODUCTION, Outcome.FAILED, Phase.GREEN, False),
        (Phase.GREEN, FileKind.PRODUCTION, Outcome.ERROR, Phase.GREEN, False),
        (Phase.REFACTOR, FileKind.PRODUCTION, Outcome.PASSED, Phase.REFACTOR, False),
        (Phase.REFACTOR, FileKind.PRODUCTION, Outcome.FAILED, Phase.REFACTOR, True),
        (Phase.REFACTOR, FileKind.TEST, Outcome.PASSED, Phase.REFACTOR, False),
        (Phase.REFACTOR, FileKind.TEST, Outcome.ERROR, Phase.REFACTOR, True),
    ],
)
def test_after_write(phase, kind, outcome, expected_phase, revert):
    transition = after_write(phase, kind, outcome)
    assert transition.phase is expected_phase
    assert transition.revert is revert


def test_disallowed_write_transition_is_rejected():
    with pytest.raises(ValueError, match="not allowed"):
        after_write(Phase.RED, FileKind.PRODUCTION, Outcome.PASSED)


def test_red_needs_exactly_one_failing_test():
    transition = after_write(
        Phase.RED, FileKind.TEST, Outcome.FAILED, failing=2, added=1
    )
    assert transition.phase is Phase.RED
    assert "2 tests fail" in transition.reason


def test_red_rejects_adding_more_than_one_test():
    transition = after_write(
        Phase.RED, FileKind.TEST, Outcome.FAILED, failing=1, added=3
    )
    assert transition.phase is Phase.RED
    assert "3 tests were added" in transition.reason


def test_refactor_that_adds_tests_is_reverted():
    transition = after_write(
        Phase.REFACTOR, FileKind.TEST, Outcome.PASSED, failing=0, added=1
    )
    assert transition.phase is Phase.REFACTOR
    assert transition.revert is True
    assert "must not add tests" in transition.reason


def test_non_code_writes_cannot_advance_the_cycle():
    with pytest.raises(ValueError, match="only code files"):
        after_write(Phase.RED, FileKind.OTHER, Outcome.FAILED)
