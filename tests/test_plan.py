import pytest

from tdd_mcp.cycle import Phase
from tdd_mcp.plan import Checklist, PlanError, PlannedTest

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
    with pytest.raises(PlanError, match="at least one test"):
        Checklist([])


def test_a_planned_test_without_an_act_or_assert_is_refused():
    vague = PlannedTest("adds", arrange="a calculator", act=" ", assertion="")
    with pytest.raises(PlanError, match="'adds' has no act or assert"):
        Checklist([ADDS, vague])


def test_planning_the_same_test_name_twice_is_refused():
    with pytest.raises(PlanError, match="'adds two numbers' is planned twice"):
        Checklist([ADDS, REJECTS, ADDS])


def test_a_planned_test_without_a_name_is_refused():
    nameless = PlannedTest(" ", arrange="a calculator", act="add", assertion="5")
    with pytest.raises(PlanError, match="A planned test has no name"):
        Checklist([nameless])


def test_the_reminder_lists_the_plan_marking_done_and_current_tests():
    checklist = Checklist([ADDS, REJECTS])
    checklist.check_off()
    assert checklist.reminder(Phase.RED).startswith(
        "Test plan (1 of 2 done):\n[x] adds two numbers\n[>] rejects negative numbers\n"
    )


def test_the_reminder_marks_tests_after_the_current_one_as_waiting():
    reminder = Checklist([ADDS, REJECTS]).reminder(Phase.RED)
    assert "[>] adds two numbers\n[ ] rejects negative numbers\n" in reminder


def test_red_reminds_to_name_the_test_after_the_plan():
    reminder = Checklist([ADDS, REJECTS]).reminder(Phase.RED)
    assert reminder.endswith(
        "Next TDD step: write only the test 'adds two numbers', with that name in "
        "its test name, nothing else. "
        "Arrange: a calculator. Act: add 2 and 3. Assert: the result is 5. "
        "Do only as much as this step needs, and no more."
    )


def test_green_reminds_to_write_only_the_code_the_current_assert_needs():
    reminder = Checklist([ADDS, REJECTS]).reminder(Phase.GREEN)
    assert reminder.endswith(
        "Next TDD step: make 'adds two numbers' pass with only the production "
        "code its assert needs (the result is 5); write nothing for the tests "
        "still waiting. Do only as much as this step needs, and no more."
    )


def test_refactor_reminds_that_advancing_checks_off_the_current_test():
    reminder = Checklist([ADDS, REJECTS]).reminder(Phase.REFACTOR)
    assert reminder.endswith(
        "Next TDD step: tidy the code without adding behaviour, commit, then "
        "call advance_tdd_phase, which checks off 'adds two numbers'. Do only "
        "as much as this step needs, and no more."
    )


def test_a_finished_plan_reminds_to_plan_only_missing_tests_or_finish():
    checklist = Checklist([ADDS])
    checklist.check_off()
    assert checklist.reminder(Phase.PLAN).endswith(
        "Next TDD step: every planned test is done. If the task still lacks a "
        "test, call plan_tests with only the missing ones; otherwise the task "
        "is finished. Do only as much as this step needs, and no more."
    )


def test_planned_test_from_reads_name_arrange_act_and_assert():
    from tdd_mcp.plan import planned_test_from

    spec = {"name": "adds", "arrange": "calc", "act": "add 1 and 2", "assert": "3"}

    assert planned_test_from(spec) == PlannedTest("adds", "calc", "add 1 and 2", "3")
