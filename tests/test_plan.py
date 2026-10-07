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
