import pytest

from tdd_mcp.plan import Checklist, PlannedTest

ADDS = PlannedTest(
    "adds two numbers",
    arrange="a calculator",
    act="add 2 and 3",
    assertion="the result is 5",
)
REJECTS = PlannedTest(
    "rejects negative numbers",
    arrange="a calculator",
    act="add -1 and 3",
    assertion="it raises ValueError",
)


def test_the_first_planned_test_is_the_current_one():
    assert Checklist([ADDS, REJECTS]).current == ADDS


def test_checking_off_the_current_test_moves_on_to_the_next():
    checklist = Checklist([ADDS, REJECTS])
    checklist.check_off()
    assert checklist.current == REJECTS


def test_a_checklist_with_every_test_checked_off_has_no_current_test():
    checklist = Checklist([ADDS])
    checklist.check_off()
    assert checklist.current is None


def test_an_empty_plan_is_refused():
    from tdd_mcp.plan import PlanError

    with pytest.raises(PlanError, match="at least one test"):
        Checklist([])
