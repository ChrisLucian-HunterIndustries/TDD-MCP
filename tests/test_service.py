from pathlib import Path, PurePath

import pytest

from tdd_mcp.cycle import FileKind, Outcome, Phase
from tdd_mcp.languages.base import Function, SuiteRun
from tdd_mcp.plan import Checklist, PlannedTest
from tdd_mcp.reports import SuiteCounts
from tdd_mcp.service import Report, TddError, TddService
from tdd_mcp.workspace import WorkspaceError


class FakeAdapter:
    """A made-up language: `test*` files are tests, `*.code` files are production."""

    name = "fake"

    def __init__(self) -> None:
        self.outcome = Outcome.PASSED
        self.counts = SuiteCounts(tests=0, failures=0)
        self.uncovered: dict[str, frozenset[int]] = {}
        self.untaken: dict[str, frozenset[int]] = {}
        self.test_runs = 0
        self.test_output = "test output"
        self.selections: list[tuple[str | None, str | None]] = []

    def classify(self, relative_path: PurePath) -> FileKind:
        if relative_path.name.startswith("test"):
            return FileKind.TEST
        if relative_path.suffix == ".code":
            return FileKind.PRODUCTION
        return FileKind.OTHER

    def comment_lines(self, source: str) -> frozenset[int]:
        return frozenset(
            number
            for number, line in enumerate(source.splitlines(), start=1)
            if "#" in line
        )

    def uncommented(self, source: str) -> dict[int, str]:
        return {
            number: line.split("#")[0].rstrip()
            for number, line in enumerate(source.splitlines(), start=1)
            if "#" in line
        }

    def definitions(self, source: str) -> frozenset[str]:
        return frozenset(
            line.split()[1] for line in source.splitlines() if line.startswith("def ")
        )

    def functions(self, source: str) -> tuple[Function, ...]:
        lines = source.splitlines()
        starts = [n for n, line in enumerate(lines, 1) if line.startswith("def ")]
        ends = [start - 1 for start in starts[1:]] + [len(lines)]
        return tuple(
            Function(lines[start - 1].split()[1], start=start, body=start + 1, end=end)
            for start, end in zip(starts, ends)
        )

    def run_tests(
        self, root: Path, path: str | None = None, test_name: str | None = None
    ) -> SuiteRun:
        self.test_runs += 1
        self.selections.append((path, test_name))
        return SuiteRun(self.outcome, self.test_output, self.counts)

    def run_coverage(self, root: Path) -> SuiteRun:
        return SuiteRun(
            self.outcome, "coverage output", self.counts, self.uncovered, self.untaken
        )


class FakeTree:
    """Reports `changes` as uncommitted, recording which roots were checked."""

    def __init__(self) -> None:
        self.changes: list[str] = []
        self.checked: list[Path] = []

    def __call__(self, root: Path) -> list[str]:
        self.checked.append(root)
        return list(self.changes)


@pytest.fixture
def adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture
def tree() -> FakeTree:
    return FakeTree()


@pytest.fixture
def service(adapter: FakeAdapter, tree: FakeTree) -> TddService:
    return TddService({"fake": adapter}, pending_changes=tree)


def _start(service: TddService, root: Path) -> Report:
    return service.advance_tdd_phase(str(root), "fake")


def test_status_before_coverage_requires_coverage(service: TddService, tmp_path: Path):
    report = service.status(str(tmp_path))
    assert report.phase is Phase.COVERAGE_REQUIRED
    assert "coverage" in report.message


def test_writing_before_coverage_is_refused(service: TddService, tmp_path: Path):
    with pytest.raises(TddError, match="No TDD cycle started"):
        service.write_file(str(tmp_path), "test_a", "x")
    assert not (tmp_path / "test_a").exists()


def test_unknown_language_is_refused(service: TddService, tmp_path: Path):
    with pytest.raises(TddError, match="Unsupported language 'cobol'.*fake"):
        service.run_coverage(str(tmp_path), "cobol")


def test_location_must_be_a_directory(service: TddService, tmp_path: Path):
    with pytest.raises(TddError, match="not a directory"):
        service.status(str(tmp_path / "missing"))


def test_passing_coverage_moves_to_red_and_includes_output(service, tmp_path: Path):
    report = _start(service, tmp_path)
    assert report.phase is Phase.RED
    assert report.output == "coverage output"
    assert service.status(str(tmp_path)).phase is Phase.RED


def test_failing_coverage_stays_coverage_required(service, adapter, tmp_path: Path):
    adapter.outcome = Outcome.FAILED
    assert _start(service, tmp_path).phase is Phase.COVERAGE_REQUIRED


def test_advancing_with_exactly_one_failing_test_resumes_green(
    service, adapter, tmp_path: Path
):
    adapter.outcome, adapter.counts = Outcome.FAILED, SuiteCounts(tests=3, failures=1)
    assert _start(service, tmp_path).phase is Phase.GREEN


def test_advancing_with_several_failing_tests_returns_to_red_to_remove_them(
    service, adapter, tmp_path: Path
):
    """Locked in coverage_required, weaker models had no tool left to remove extra tests."""
    adapter.outcome, adapter.counts = Outcome.FAILED, SuiteCounts(tests=3, failures=3)

    report = _start(service, tmp_path)

    assert report.phase is Phase.RED
    assert "3 tests fail" in report.message
    assert "write exactly ONE new test" not in report.message


def test_run_coverage_reports_without_advancing_the_phase(service, tmp_path: Path):
    report = service.run_coverage(str(tmp_path), "fake")

    assert report.phase is Phase.COVERAGE_REQUIRED
    assert "phase unchanged" in report.message
    assert "advance_tdd_phase" in report.message
    assert report.output == "coverage output"
    assert service.status(str(tmp_path)).phase is Phase.COVERAGE_REQUIRED


def test_full_cycle(service: TddService, adapter: FakeAdapter, tmp_path: Path):
    location = str(tmp_path)
    _start(service, tmp_path)

    with pytest.raises(TddError, match="not allowed in the red phase"):
        service.write_file(location, "calc.code", "impl")
    assert not (tmp_path / "calc.code").exists()

    adapter.outcome = Outcome.FAILED
    report = service.write_file(location, "test_calc", "test")
    assert report.phase is Phase.GREEN
    assert report.output == "test output"

    with pytest.raises(TddError, match="not allowed in the green phase"):
        service.write_file(location, "test_calc", "weakened test")
    assert (tmp_path / "test_calc").read_text() == "test"

    adapter.outcome = Outcome.PASSED
    assert service.write_file(location, "calc.code", "impl").phase is Phase.REFACTOR

    assert (
        service.edit_file(location, "calc.code", "impl", "better").phase
        is Phase.REFACTOR
    )
    assert (tmp_path / "calc.code").read_text() == "better"

    assert _start(service, tmp_path).phase is Phase.RED


def test_return_to_red_unlocks_tests_that_assert_the_old_behaviour(
    service, adapter, tmp_path: Path
):
    _start(service, tmp_path)
    adapter.outcome = Outcome.FAILED
    service.write_file(str(tmp_path), "test_new", "new behaviour")

    assert service.return_to_red(str(tmp_path)).phase is Phase.RED
    assert (
        service.write_file(str(tmp_path), "test_old", "loosened").phase is Phase.GREEN
    )


def test_return_to_red_is_refused_outside_green(service, adapter, tmp_path: Path):
    _to_refactor(service, adapter, tmp_path)

    with pytest.raises(TddError, match="only from the green phase.*refactor phase"):
        service.return_to_red(str(tmp_path))
    assert service.status(str(tmp_path)).phase is Phase.REFACTOR


def test_return_to_red_waits_until_green_edits_are_undone(
    service, adapter, tree, tmp_path: Path
):
    _start(service, tmp_path)
    adapter.outcome = Outcome.FAILED
    service.write_file(str(tmp_path), "test_new", "new behaviour")
    tree.changes = [" M calc.code"]

    with pytest.raises(TddError, match=r"Uncommitted changes .*M calc\.code\. Undo"):
        service.return_to_red(str(tmp_path))
    assert service.status(str(tmp_path)).phase is Phase.GREEN


def test_passing_new_test_stays_red_and_keeps_file(service, tmp_path: Path):
    _start(service, tmp_path)
    report = service.write_file(str(tmp_path), "test_calc", "test")
    assert report.phase is Phase.RED
    assert "fails" in report.message
    assert (tmp_path / "test_calc").read_text() == "test"


def test_red_write_adding_two_tests_stays_red(service, adapter, tmp_path: Path):
    adapter.counts = SuiteCounts(tests=5, failures=0)
    _start(service, tmp_path)
    adapter.outcome = Outcome.FAILED
    adapter.counts = SuiteCounts(tests=7, failures=1)

    report = service.write_file(str(tmp_path), "test_calc", "two new tests")

    assert report.phase is Phase.RED
    assert "2 tests were added" in report.message


def test_red_write_with_extra_tests_does_not_ask_for_another_test(
    service, adapter, tmp_path: Path
):
    """Gemma4 followed the generic "write exactly ONE new test" and kept adding tests."""
    _start(service, tmp_path)
    adapter.outcome, adapter.counts = Outcome.FAILED, SuiteCounts(tests=3, failures=3)

    report = service.write_file(str(tmp_path), "test_calc", "three failing tests")

    assert report.phase is Phase.RED
    assert "write exactly ONE new test" not in report.message
    assert "delete extra new tests entirely" in report.message
    assert "call rollback_cycle" in report.message
    assert "code that doesn't exist yet is a valid failing test" in report.message


def test_advancing_refreshes_the_guidance_locked_writes_repeat(
    service, adapter, tmp_path: Path
):
    _start(service, tmp_path)
    adapter.outcome, adapter.counts = Outcome.FAILED, SuiteCounts(tests=2, failures=2)
    service.write_file(str(tmp_path), "test_calc", "two failing tests")
    adapter.outcome, adapter.counts = Outcome.PASSED, SuiteCounts(tests=2, failures=0)
    _start(service, tmp_path)

    with pytest.raises(TddError, match="write exactly ONE new test"):
        service.write_file(str(tmp_path), "calc.code", "impl")


def test_advancing_cannot_carry_extra_new_tests_into_green(
    service, adapter, tmp_path: Path
):
    """Advancing used to reset the new-test count, letting several new tests reach green."""
    location = str(tmp_path)
    _start(service, tmp_path)
    adapter.outcome, adapter.counts = Outcome.FAILED, SuiteCounts(tests=3, failures=1)
    service.write_file(location, "test_calc", "one failing and two passing tests")

    report = _start(service, tmp_path)

    assert report.phase is Phase.RED
    assert "3 tests were added" in report.message
    assert "delete extra new tests entirely" in report.message
    assert service.write_file(location, "test_calc", "unchanged").phase is Phase.RED
    adapter.counts = SuiteCounts(tests=1, failures=1)
    assert service.write_file(location, "test_calc", "one test").phase is Phase.GREEN


def test_coverage_run_without_counts_keeps_the_test_baseline(
    service, adapter, tmp_path: Path
):
    adapter.counts = SuiteCounts(tests=5, failures=0)
    _start(service, tmp_path)
    adapter.counts = None
    _start(service, tmp_path)
    adapter.outcome = Outcome.FAILED
    adapter.counts = SuiteCounts(tests=6, failures=1)

    report = service.write_file(str(tmp_path), "test_calc", "one new test")

    assert report.phase is Phase.GREEN


def test_refactor_counts_the_cycles_new_test_as_existing(
    service, adapter, tmp_path: Path
):
    adapter.counts = SuiteCounts(tests=1, failures=0)
    _start(service, tmp_path)
    adapter.outcome, adapter.counts = Outcome.FAILED, SuiteCounts(tests=2, failures=1)
    service.write_file(str(tmp_path), "test_calc", "test")
    adapter.outcome, adapter.counts = Outcome.PASSED, SuiteCounts(tests=2, failures=0)
    service.write_file(str(tmp_path), "calc.code", "impl")

    report = service.edit_file(str(tmp_path), "calc.code", "impl", "tidy")

    assert "was reverted" not in report.message
    assert (tmp_path / "calc.code").read_text() == "tidy"


def test_a_failed_edit_says_nothing_was_written_and_what_the_phase_needs(
    service: TddService, tmp_path: Path
):
    """After an edit error, weak models lost track of where they were in the cycle."""
    (tmp_path / "test_calc").write_text("x = 1\n")
    _start(service, tmp_path)

    with pytest.raises(WorkspaceError) as refusal:
        service.edit_file(str(tmp_path), "test_calc", "y = 2", "y = 3")

    assert "Nothing was written. You are in the red phase." in str(refusal.value)
    assert "To move on to green:" in str(refusal.value)


def test_editing_a_missing_file_says_so_before_any_phase_refusal(
    service: TddService, tree: FakeTree, tmp_path: Path
):
    """Gemma4 edited a never-created file three times, hearing only "uncommitted"."""
    _start(service, tmp_path)
    tree.changes = [" M test_calc"]

    with pytest.raises(WorkspaceError, match="does not exist.*write_file"):
        service.edit_file(str(tmp_path), "calc.code", "a", "b")


def test_an_uncommitted_step_refusal_names_the_exact_commit(
    service: TddService, adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Gemma4 committed its red step as a refactoring, listing a file that didn't exist."""
    (tmp_path / "calc.code").write_text("impl")
    _start(service, tmp_path)
    adapter.outcome = Outcome.FAILED
    service.write_file(str(tmp_path), "test_calc", "test")
    tree.changes = ["?? test_calc"]

    with pytest.raises(TddError) as refusal:
        service.edit_file(str(tmp_path), "calc.code", "impl", "done")

    assert (
        "commit them as '. t' (racn intention test_only, risk proven_safe, "
        'paths ["test_calc"])' in str(refusal.value)
    )


def test_a_production_write_in_red_says_a_missing_code_failure_is_the_goal(
    service: TddService, tmp_path: Path
):
    """Gemma4 called its test's ModuleNotFoundError "stuck" and faked the class in the test."""
    _start(service, tmp_path)

    with pytest.raises(TddError, match="Don't define stand-ins.*in the test file"):
        service.write_file(str(tmp_path), "calc.code", "impl")


def test_a_production_write_in_red_leads_with_the_extra_tests_to_delete(
    service: TddService, adapter: FakeAdapter, tmp_path: Path
):
    """Gemma4 retried tictactoe.py 8 times; only an older reply said to delete 2 tests."""
    _start(service, tmp_path)
    adapter.outcome = Outcome.FAILED
    adapter.counts = SuiteCounts(tests=3, failures=3)
    service.write_file(str(tmp_path), "test_calc", "three tests")

    with pytest.raises(TddError) as refusal:
        service.write_file(str(tmp_path), "calc.code", "impl")

    message = str(refusal.value)
    assert message.startswith(
        "Writing production files is not allowed in the red phase. Production is "
        "locked because 3 new tests were added; red needs exactly one. Next: "
        "delete 2 of the new test functions"
    )
    assert "rollback_cycle" not in message


def test_retrying_a_refused_call_unchanged_says_it_will_be_refused_again(
    service: TddService, tmp_path: Path
):
    """Gemma4 sent the same refused write_file 8 times."""
    _start(service, tmp_path)
    with pytest.raises(TddError) as first:
        service.write_file(str(tmp_path), "calc.code", "impl")

    with pytest.raises(TddError) as retry:
        service.write_file(str(tmp_path), "calc.code", "impl")

    assert "already refused" not in str(first.value)
    assert str(retry.value).startswith(
        "This exact call was already refused, and retrying it unchanged is "
        "refused the same way. "
    )


def test_a_new_test_failing_on_an_unimported_name_says_to_import_it(
    service: TddService, adapter: FakeAdapter, tmp_path: Path
):
    """Gemma4's first test never imported TicTacToe; it rewrote production 5 times."""
    _start(service, tmp_path)
    adapter.outcome = Outcome.FAILED
    adapter.counts = SuiteCounts(tests=1, failures=1)
    adapter.test_output = "test_calc:4: in test_new_game\nE   NameError: name 'TicTacToe' is not defined\n"

    report = service.write_file(str(tmp_path), "test_calc", "uses TicTacToe")

    assert report.phase is Phase.GREEN
    assert (
        "The new test fails because TicTacToe is not defined in it. Production "
        "code can't fix that: the test must import TicTacToe. Fix the test now; "
        "it stays editable until you commit it as '. t'."
    ) in report.message


def test_a_new_typescript_test_failing_on_an_unimported_name_says_to_import_it(
    service: TddService, adapter: FakeAdapter, tmp_path: Path
):
    _start(service, tmp_path)
    adapter.outcome = Outcome.FAILED
    adapter.counts = SuiteCounts(tests=1, failures=1)
    adapter.test_output = "ReferenceError: TicTacToe is not defined\n"

    report = service.write_file(str(tmp_path), "test_calc", "uses TicTacToe")

    assert "the test must import TicTacToe" in report.message


def test_a_test_write_in_green_names_return_to_red_for_a_wrong_new_test(
    service: TddService, adapter: FakeAdapter, tmp_path: Path
):
    """Told to fix a wrong test "later, in refactor", Gemma4 never reached refactor."""
    _start(service, tmp_path)
    adapter.outcome = Outcome.FAILED
    adapter.counts = SuiteCounts(tests=1, failures=1)
    service.write_file(str(tmp_path), "test_calc", "missing import")

    with pytest.raises(TddError) as refusal:
        service.write_file(str(tmp_path), "test_calc", "with import")

    assert (
        "If the new test itself is wrong (e.g. it doesn't import what it uses), "
        "no production change can make it pass: call return_to_red and fix it there."
    ) in str(refusal.value)


def test_return_to_red_lets_a_wrong_new_test_be_fixed(
    service: TddService, adapter: FakeAdapter, tmp_path: Path
):
    _start(service, tmp_path)
    adapter.outcome = Outcome.FAILED
    adapter.counts = SuiteCounts(tests=1, failures=1)
    service.write_file(str(tmp_path), "test_calc", "missing import")

    report = service.return_to_red(str(tmp_path))

    assert "fix the new test if it's wrong (e.g. add a missing import)" in (
        report.message
    )
    assert service.write_file(str(tmp_path), "test_calc", "with import").phase is (
        Phase.GREEN
    )


def test_write_file_refuses_content_that_drops_existing_definitions(
    service: TddService, adapter: FakeAdapter, tmp_path: Path
):
    """Gemma4 wrote only a new method with write_file, wiping out its whole class."""
    _to_refactor(service, adapter, tmp_path)
    (tmp_path / "calc.code").write_text("def add\ndef sub\n")

    with pytest.raises(TddError) as refusal:
        service.write_file(str(tmp_path), "calc.code", "def add\n")

    assert (
        "write_file replaces the whole file, and this content drops sub from "
        "calc.code. Use edit_file to add, change or delete code"
    ) in str(refusal.value)
    assert (tmp_path / "calc.code").read_text() == "def add\ndef sub\n"
    assert "Nothing was written. You are in the refactor phase." in str(refusal.value)


class FakeHistory:
    def __init__(self) -> None:
        self.head = "base"
        self.changed: dict[str, frozenset[int]] = {}
        self.ancestor = True
        self.rolled_back_to: list[str] = []

    def head_commit(self, root: Path) -> str:
        return self.head

    def is_ancestor(self, root: Path, commit: str) -> bool:
        return self.ancestor

    def rollback(self, root: Path, commit: str) -> str:
        backup = f"refs/tdd-mcp/rollback-{self.head}"
        self.rolled_back_to.append(commit)
        self.head = commit
        return backup

    def changed_lines(self, root: Path, base: str) -> dict[str, frozenset[int]]:
        assert base == "base"
        return self.changed

    def set_aside(self, root: Path, paths: list[str]) -> None:
        self.set_aside_paths = paths


def test_return_to_red_with_the_red_step_open_says_to_just_edit_the_test(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _start(service, tmp_path)
    adapter.outcome, adapter.counts = Outcome.FAILED, SuiteCounts(tests=1, failures=1)
    service.write_file(str(tmp_path), "test_calc", "test")
    tree.changes = ["?? test_calc"]

    with pytest.raises(TddError) as refusal:
        service.return_to_red(str(tmp_path))

    assert (
        "The red step's test changes (test_calc) aren't committed yet, so the "
        "test is still editable: fix it with edit_file now, without return_to_red, "
        "then commit it as '. t'."
    ) in str(refusal.value)


def test_return_to_red_sets_aside_new_production_files_it_cannot_ask_to_undo(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Told to "edit back" a new file, Gemma4 had no tool to delete it: a dead end."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _start(service, tmp_path)
    adapter.outcome, adapter.counts = Outcome.FAILED, SuiteCounts(tests=1, failures=1)
    service.write_file(str(tmp_path), "test_calc", "test")
    service.write_file(str(tmp_path), "calc.code", "wrong")
    tree.changes = ["?? calc.code"]

    report = service.return_to_red(str(tmp_path))

    assert report.phase is Phase.RED
    assert history.set_aside_paths == ["calc.code"]
    assert (
        "Your uncommitted production changes (calc.code) were set aside in git "
        "stash ('tdd-mcp return_to_red')"
    ) in report.message


def test_coverage_holds_the_phase_while_changed_production_lines_are_untested(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    history.changed = {"calc.code": frozenset({1, 2, 3}), "test_calc": frozenset({1})}
    adapter.uncovered = {"calc.code": frozenset({3, 9}), "test_calc": frozenset({1})}

    report = _start(service, tmp_path)

    assert report.phase is Phase.REFACTOR
    assert "calc.code: 3." in report.message
    assert "test_calc" not in report.message


def test_a_blocked_advance_quotes_the_untested_lines_to_delete(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Gemma4 couldn't map bare line numbers to text: its file reader shows none."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    (tmp_path / "calc.code").write_text("impl\nused()\n    dead()\n")
    history.changed = {"calc.code": frozenset({2, 3})}
    adapter.uncovered = {"calc.code": frozenset({3})}

    report = _start(service, tmp_path)

    assert "\ncalc.code:3:     dead()\n" in report.message
    assert "used()" not in report.message


def test_a_blocked_advance_calls_the_fix_routine_and_says_to_carry_on(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Gemma4 read "this isn't normal progress" as a reason to stop and ask."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    history.changed = {"calc.code": frozenset({3})}
    adapter.uncovered = {"calc.code": frozenset({3})}

    report = _start(service, tmp_path)

    assert "isn't normal progress" not in report.message
    assert (
        "This is a routine fix: simplify the code now with edit_file until only what "
        "your tests need remains (deleting those lines, or replacing a body with the "
        "simplest code that passes)" in report.message
    )
    assert "carry on with the task; don't stop or hand back to the user." in (
        report.message
    )


def test_a_blocked_advance_quotes_functions_that_never_run_as_whole_blocks(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Deleting only Gemma4's listed lines would leave bodiless defs, which reverts."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    (tmp_path / "calc.code").write_text(
        "def used\n  run\n  skipped\ndef dead\n  never\n"
    )
    history.changed = {"calc.code": frozenset({1, 2, 3, 4, 5})}
    adapter.uncovered = {"calc.code": frozenset({3, 5})}

    report = _start(service, tmp_path)

    assert "\ncalc.code:3:   skipped\n" in report.message
    assert "calc.code:5:" not in report.message
    assert (
        " These functions never run, so delete each one whole, its first line "
        "included (edit_file with the quoted text as old_string and an empty "
        "new_string; if that leaves a class or block empty, delete it too):\n"
        "calc.code lines 4-5:\ndef dead\n  never\n"
    ) in report.message


def test_a_green_write_that_passes_reports_lines_the_test_never_runs(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Gemma4 wrote a 37-line class in green and heard about it only two steps later."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _start(service, tmp_path)
    adapter.outcome, adapter.counts = Outcome.FAILED, SuiteCounts(tests=1, failures=1)
    service.write_file(str(tmp_path), "test_calc", "test")
    adapter.outcome, adapter.counts = Outcome.PASSED, SuiteCounts(tests=1, failures=0)
    history.changed = {"calc.code": frozenset({1, 2, 3})}
    adapter.uncovered = {"calc.code": frozenset({3})}

    report = service.write_file(
        str(tmp_path), "calc.code", "def add\n  used\n  extra\n"
    )

    assert report.phase is Phase.REFACTOR
    assert (
        " Your test doesn't run these production lines: calc.code: 3.\n"
        "calc.code:3:   extra\n Simplify the code now with edit_file until only "
        "what your test needs remains, often the simplest code that passes (e.g. "
        "returning a constant); this green step stays open until you commit it as "
        "'^ f'."
    ) in report.message


def test_an_edit_breaking_tests_after_green_passed_is_reverted(
    service: TddService, adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Gemma4's half-deletion broke the passing test and was left in place, so it spiralled."""
    _start(service, tmp_path)
    adapter.outcome, adapter.counts = Outcome.FAILED, SuiteCounts(tests=1, failures=1)
    service.write_file(str(tmp_path), "test_calc", "test")
    adapter.outcome, adapter.counts = Outcome.PASSED, SuiteCounts(tests=1, failures=0)
    service.write_file(str(tmp_path), "calc.code", "works")
    tree.changes = [" M calc.code"]
    adapter.outcome, adapter.counts = Outcome.FAILED, SuiteCounts(tests=1, failures=1)

    report = service.edit_file(str(tmp_path), "calc.code", "works", "broken")

    assert report.phase is Phase.REFACTOR
    assert "calc.code was reverted" in report.message
    assert (tmp_path / "calc.code").read_text() == "works"


def test_a_blocked_advance_explains_branches_that_never_run(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Gemma4 deleted only the flagged `if` line, leaving its body to run every time."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    (tmp_path / "calc.code").write_text(
        "def empty\n  for cell\n    if cell\n      return no\n  return yes\n"
    )
    history.changed = {"calc.code": frozenset({1, 2, 3, 4, 5})}
    adapter.uncovered = {"calc.code": frozenset({3, 4})}
    adapter.untaken = {"calc.code": frozenset({3})}

    report = _start(service, tmp_path)

    assert (
        "\ncalc.code:4:       return no\n These lines run, but one of their branches "
        "never does (e.g. an if whose condition is never true in any test):\n"
        "calc.code:3:     if cell\n Remove each such condition together with the "
        "code it guards, then simplify what's left (e.g. an emptied loop) so the "
        "test still passes."
    ) in report.message
    assert report.message.count("calc.code:3:") == 1


def test_a_function_whose_first_line_only_skips_a_branch_is_not_called_dead(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Gemma4 deleted make_move as "never runs" although its test called it."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    (tmp_path / "calc.code").write_text(
        "def move\n  if free\n    take\n    return yes\n  return no\n"
    )
    history.changed = {"calc.code": frozenset({1, 2, 3, 4, 5})}
    adapter.uncovered = {"calc.code": frozenset({2, 5})}
    adapter.untaken = {"calc.code": frozenset({2})}

    report = _start(service, tmp_path)

    assert "never run, so delete each one whole" not in report.message
    assert "\ncalc.code:5:   return no\n" in report.message


def test_a_refactor_write_adding_code_no_test_runs_says_so_at_once(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Gemma4 wrote all of check_winner in refactor and heard about it two steps later."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    history.changed = {"calc.code": frozenset({1, 2})}
    adapter.uncovered = {"calc.code": frozenset({2})}

    report = service.write_file(str(tmp_path), "calc.code", "impl\nnew feature\n")

    assert report.phase is Phase.REFACTOR
    assert (
        " Refactoring can't add behaviour, and no test runs these production "
        "lines: calc.code: 2.\ncalc.code:2: new feature\n New behaviour needs its "
        "own cycle: take it out now with edit_file, commit, call "
        "advance_tdd_phase, then write its failing test first."
    ) in report.message


def test_a_blocked_advance_frames_deleting_as_the_way_to_test_it_and_says_not_done(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Gemma4 wouldn't delete its finished-looking engine, so it declared the kata done."""
    from tdd_mcp.cycle import DONE

    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    history.changed = {"calc.code": frozenset({3})}
    adapter.uncovered = {"calc.code": frozenset({3})}

    report = _start(service, tmp_path)

    assert (
        "Deleting this code is how you get to test it: tests can only be added in "
        "red, and red starts once the untested code is gone. The code quoted above "
        "is your copy: bring it back in green, one tested behaviour per cycle."
    ) in report.message
    assert DONE in report.message


def test_a_test_added_in_refactor_while_advance_is_blocked_says_what_to_clear_first(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Told to advance before adding tests, Gemma4 hit the block and declared the kata done."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    history.changed = {"calc.code": frozenset({3})}
    adapter.uncovered = {"calc.code": frozenset({3})}
    _start(service, tmp_path)
    adapter.counts = SuiteCounts(tests=1, failures=0)

    report = service.write_file(str(tmp_path), "test_calc", "a new test")

    assert "test_calc was reverted" in report.message
    assert (
        " advance_tdd_phase is blocked right now, so first clear what it flagged "
        "(delete the untested code, remove the comments), commit, and advance; "
        "then add this test in red, one test per cycle."
    ) in report.message


def test_a_repeated_blocked_advance_says_nothing_changed(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Gemma4 advanced twice without deleting anything, then handed back to the user."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    history.changed = {"calc.code": frozenset({3})}
    adapter.uncovered = {"calc.code": frozenset({3})}
    repeat = (
        "Nothing changed since your last advance_tdd_phase: the same lines are "
        "still flagged. Fix them before advancing again."
    )

    first = _start(service, tmp_path)
    second = _start(service, tmp_path)

    assert repeat not in first.message
    assert repeat in second.message


def test_a_blocked_advance_leads_with_the_block_not_optional_tidying(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Gemma4 read "Coverage run passed" and "optionally tidy", and called 18% coverage normal."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    history.changed = {"calc.code": frozenset({3})}
    adapter.uncovered = {"calc.code": frozenset({3})}

    report = _start(service, tmp_path)

    assert report.message.startswith("Tests passed, but the next cycle is blocked.")
    assert "optionally" not in report.message


def test_advancing_holds_the_phase_while_changed_lines_hold_comments(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    (tmp_path / "calc.code").write_text("impl\n# why\n# older\n")
    (tmp_path / "test_calc").write_text("# explains the test\n")
    (tmp_path / "notes.md").write_text("# heading\n")
    history.changed = {
        "calc.code": frozenset({1, 2}),
        "test_calc": frozenset({1}),
        "notes.md": frozenset({1}),
    }

    report = _start(service, tmp_path)

    assert report.phase is Phase.REFACTOR
    assert "calc.code: 2; test_calc: 1." in report.message
    assert "notes.md" not in report.message
    assert "\ncalc.code:2: # why\ntest_calc:1: # explains the test\n" in report.message


def test_a_blocked_advance_in_red_keeps_the_cycle_start(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Gemma4 committed flagged comments in red; the next advance then let them through."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _start(service, tmp_path)
    (tmp_path / "test_calc").write_text("# explains the test\n")
    history.changed = {"test_calc": frozenset({1})}
    history.head = "comments committed"

    _start(service, tmp_path)
    report = _start(service, tmp_path)

    assert "test_calc:1: # explains the test" in report.message


def test_a_comment_after_code_says_to_keep_the_code(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """Gemma4 deleted `p_x, p_y = 0, 1  # Example...` whole, breaking its test."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    (tmp_path / "test_calc").write_text("# why\nx = 1  # example\n")
    history.changed = {"test_calc": frozenset({1, 2})}

    report = _start(service, tmp_path)

    assert (
        " Keep the code on these lines and drop only the comment, so each line "
        "becomes:\ntest_calc:2: x = 1\n"
    ) in report.message
    assert "test_calc:1: \n" not in report.message


def test_a_reset_past_the_cycle_start_resyncs_instead_of_flagging_old_code(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    history.changed = {"calc.code": frozenset({3})}
    adapter.uncovered = {"calc.code": frozenset({3})}
    history.ancestor = False

    assert _start(service, tmp_path).phase is Phase.RED


def _to_refactor(service: TddService, adapter: FakeAdapter, root: Path) -> None:
    _start(service, root)
    adapter.outcome = Outcome.FAILED
    service.write_file(str(root), "test_calc", "test")
    adapter.outcome = Outcome.PASSED
    service.write_file(str(root), "calc.code", "impl")


def test_rollback_cycle_resets_to_the_cycle_start_and_restarts_in_red(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    """A model stuck mid-cycle can always get back to where every test passed."""
    history = FakeHistory()
    service = TddService({"fake": adapter}, pending_changes=tree, history=history)
    _to_refactor(service, adapter, tmp_path)
    history.head = "later"

    report = service.rollback_cycle(str(tmp_path))

    assert history.rolled_back_to == ["base"]
    assert report.phase is Phase.RED
    assert "refs/tdd-mcp/rollback-later" in report.message


def test_rollback_cycle_without_a_recorded_cycle_start_is_refused(
    service, adapter, tmp_path: Path
):
    _start(service, tmp_path)

    with pytest.raises(TddError, match="No cycle start commit to roll back to"):
        service.rollback_cycle(str(tmp_path))
    assert service.status(str(tmp_path)).phase is Phase.RED


def test_a_passing_write_omits_the_runner_output_to_save_context(
    service, adapter, tmp_path: Path
):
    """Small local models run with limited context; a pass needs no log."""
    _start(service, tmp_path)
    adapter.outcome = Outcome.FAILED
    service.write_file(str(tmp_path), "test_calc", "test")
    adapter.outcome = Outcome.PASSED

    report = service.write_file(str(tmp_path), "calc.code", "impl")

    assert report.phase is Phase.REFACTOR
    assert report.output == ""


def test_breaking_refactor_is_reverted(service, adapter, tmp_path: Path):
    _to_refactor(service, adapter, tmp_path)
    adapter.outcome = Outcome.FAILED

    report = service.edit_file(str(tmp_path), "calc.code", "impl", "broken")

    assert report.phase is Phase.REFACTOR
    assert "reverted" in report.message
    assert (tmp_path / "calc.code").read_text() == "impl"


def test_breaking_refactor_creating_new_file_is_removed(
    service, adapter, tmp_path: Path
):
    _to_refactor(service, adapter, tmp_path)
    adapter.outcome = Outcome.ERROR

    service.write_file(str(tmp_path), "extracted.code", "broken")

    assert not (tmp_path / "extracted.code").exists()


def test_non_code_files_are_written_without_running_tests(
    service, adapter, tmp_path: Path
):
    adapter.outcome = Outcome.FAILED
    _start(service, tmp_path)

    report = service.write_file(str(tmp_path), "notes.md", "hello")

    assert report.phase is Phase.COVERAGE_REQUIRED
    assert (tmp_path / "notes.md").read_text() == "hello"
    assert adapter.test_runs == 0


@pytest.mark.parametrize("path", ["scripts/deploy.code", "scripts/test_deploy"])
def test_exempt_paths_skip_the_cycle(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path, path: str
):
    service = TddService({"fake": adapter}, pending_changes=tree, exempt=("scripts/*",))
    _start(service, tmp_path)

    report = service.write_file(str(tmp_path), path, "x")

    assert report.phase is Phase.RED
    assert "exempt" in report.message
    assert (tmp_path / path).read_text() == "x"
    assert adapter.test_runs == 0


def test_exempt_patterns_do_not_match_other_paths(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    service = TddService({"fake": adapter}, pending_changes=tree, exempt=("scripts/*",))
    _start(service, tmp_path)
    with pytest.raises(TddError, match="not allowed in the red phase"):
        service.write_file(str(tmp_path), "src/calc.code", "x")


@pytest.mark.parametrize("edit", ["write_file", "edit_file"])
@pytest.mark.parametrize("path", ["test_calc", "notes.md", "scripts/tool.code"])
def test_edits_are_refused_while_changes_are_uncommitted(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path, edit: str, path: str
):
    service = TddService({"fake": adapter}, pending_changes=tree, exempt=("scripts/*",))
    (tmp_path / "scripts").mkdir()
    (tmp_path / path).write_text("old")
    _start(service, tmp_path)
    tree.changes = [" M test_calc", "?? notes.md"]

    with pytest.raises(
        TddError, match=r"Uncommitted changes .*: M test_calc, \?\? notes\.md\. Commit"
    ):
        if edit == "write_file":
            service.write_file(str(tmp_path), path, "new")
        else:
            service.edit_file(str(tmp_path), path, "old", "new")

    assert (tmp_path / path).read_text() == "old"
    assert adapter.test_runs == 0
    assert tree.checked == [tmp_path.resolve()]


def test_a_locked_file_reports_the_lock_before_uncommitted_changes(
    service, adapter, tree, tmp_path: Path
):
    """Committing can't unlock it, so asking for a commit first sends models in circles."""
    adapter.outcome = Outcome.FAILED
    _start(service, tmp_path)
    tree.changes = ["?? test_calc"]

    with pytest.raises(TddError, match="not allowed in the coverage_required phase"):
        service.write_file(str(tmp_path), "calc.code", "impl")


def test_an_uncommitted_red_step_can_be_amended(service, adapter, tree, tmp_path: Path):
    _start(service, tmp_path)
    adapter.outcome, adapter.counts = Outcome.FAILED, SuiteCounts(tests=1, failures=1)
    service.write_file(str(tmp_path), "test_calc", "failing for the wrong reason")
    tree.changes = ["?? test_calc"]

    report = service.write_file(str(tmp_path), "test_calc", "failing for the right one")

    assert report.phase is Phase.GREEN
    assert (tmp_path / "test_calc").read_text() == "failing for the right one"


def test_a_coverage_run_ends_the_uncommitted_step(
    service, adapter, tree, tmp_path: Path
):
    _to_refactor(service, adapter, tmp_path)
    service.edit_file(str(tmp_path), "calc.code", "impl", "tidy")
    tree.changes = [" M calc.code"]
    _start(service, tmp_path)

    with pytest.raises(TddError, match="Uncommitted changes"):
        service.write_file(str(tmp_path), "test_next", "next test")


def test_only_edits_are_gated(service, adapter, tree, tmp_path: Path):
    tree.changes = ["?? notes.md"]

    _start(service, tmp_path)
    service.run_tests(str(tmp_path))
    service.status(str(tmp_path))

    assert adapter.test_runs == 1
    assert tree.checked == []


def test_run_tests_requires_a_started_cycle(service: TddService, tmp_path: Path):
    with pytest.raises(TddError, match="No TDD cycle started"):
        service.run_tests(str(tmp_path))


def test_run_tests_never_advances_the_phase(service, adapter, tmp_path: Path):
    _start(service, tmp_path)
    adapter.outcome = Outcome.FAILED
    service.write_file(str(tmp_path), "test_calc", "test")
    adapter.outcome = Outcome.PASSED

    report = service.run_tests(str(tmp_path))

    assert report.phase is Phase.GREEN
    assert "phase unchanged" in report.message
    assert report.output == "test output"


def test_run_tests_passes_root_relative_selection(service, adapter, tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc").write_text("")
    _start(service, tmp_path)

    service.run_tests(str(tmp_path))
    service.run_tests(str(tmp_path), str(tmp_path / "tests" / "test_calc"), "adds")
    service.run_tests(str(tmp_path), "tests", None)
    service.run_tests(str(tmp_path), test_name="adds")

    assert adapter.selections == [
        (None, None),
        ("tests/test_calc", "adds"),
        ("tests", None),
        (None, "adds"),
    ]


def test_run_tests_rejects_missing_path(service, tmp_path: Path):
    _start(service, tmp_path)
    with pytest.raises(TddError, match="does not exist"):
        service.run_tests(str(tmp_path), "tests/missing")


def test_run_tests_rejects_path_outside_root(service, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    _start(service, root)
    with pytest.raises(WorkspaceError, match="outside"):
        service.run_tests(str(root), "..")


@pytest.mark.parametrize(
    ("path", "test_name"), [("-p", None), (None, "-p evil"), (None, "--co")]
)
def test_run_tests_rejects_option_like_selections(
    service, adapter, tmp_path: Path, path, test_name
):
    (tmp_path / "-p").write_text("")
    _start(service, tmp_path)
    with pytest.raises(TddError, match="must not start with '-'"):
        service.run_tests(str(tmp_path), path, test_name)
    assert adapter.test_runs == 0


def test_paths_outside_root_are_refused(service, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    _start(service, root)
    with pytest.raises(WorkspaceError):
        service.write_file(str(root), "../test_escape", "x")
    assert not (tmp_path / "test_escape").exists()


def test_sessions_are_per_location(service, tmp_path: Path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    _start(service, first)
    assert service.status(str(second)).phase is Phase.COVERAGE_REQUIRED


def test_render_shows_phase_message_and_output_tail():
    report = Report(Phase.RED, "Write a test.", "x" * 10_000 + "END")
    rendered = report.render()
    assert rendered.startswith("Phase: red\nWrite a test.\n\n")
    assert rendered.endswith("END")
    assert len(rendered) < 7_000


def test_render_without_output():
    assert Report(Phase.RED, "Write a test.").render() == "Phase: red\nWrite a test."


@pytest.fixture
def planning(adapter: FakeAdapter, tree: FakeTree) -> TddService:
    return TddService({"fake": adapter}, pending_changes=tree, require_plan=True)


def test_a_session_that_requires_a_plan_starts_in_the_plan_phase(
    planning, tmp_path: Path
):
    report = _start(planning, tmp_path)
    assert report.phase is Phase.PLAN
    assert "call plan_tests" in report.message


def test_writing_a_test_before_planning_is_refused(planning, tmp_path: Path):
    _start(planning, tmp_path)
    with pytest.raises(TddError, match="not allowed in the plan phase.*plan_tests"):
        planning.write_file(str(tmp_path), "test_calc", "test")
    assert not (tmp_path / "test_calc").exists()


ADDS = PlannedTest("adds", arrange="a calculator", act="add 2 and 3", assertion="5")
NEGATIVE = PlannedTest(
    "negative", arrange="a calculator", act="add -1", assertion="error"
)


def test_planning_tests_moves_to_red_and_reminds_of_the_first_test(
    planning, tmp_path: Path
):
    _start(planning, tmp_path)
    report = planning.plan_tests(str(tmp_path), [ADDS, NEGATIVE])
    assert report.phase is Phase.RED
    assert "Next TDD step: write only the test 'adds'" in report.message
    assert planning.status(str(tmp_path)).phase is Phase.RED


def test_planning_outside_the_plan_phase_is_refused(planning, tmp_path: Path):
    _start(planning, tmp_path)
    planning.plan_tests(str(tmp_path), [ADDS])
    with pytest.raises(TddError, match="only in the plan phase; you are in the red"):
        planning.plan_tests(str(tmp_path), [NEGATIVE])


def test_advancing_with_planned_tests_waiting_stays_in_red(planning, tmp_path: Path):
    _start(planning, tmp_path)
    planning.plan_tests(str(tmp_path), [ADDS])
    assert _start(planning, tmp_path).phase is Phase.RED


def test_advancing_ends_with_the_plan_and_its_next_step(planning, tmp_path: Path):
    _start(planning, tmp_path)
    planning.plan_tests(str(tmp_path), [ADDS, NEGATIVE])
    report = _start(planning, tmp_path)
    assert report.message.endswith(Checklist([ADDS, NEGATIVE]).reminder(Phase.RED))


def test_finishing_a_cycle_checks_off_the_planned_test(
    planning, adapter: FakeAdapter, tmp_path: Path
):
    _start(planning, tmp_path)
    planning.plan_tests(str(tmp_path), [ADDS, NEGATIVE])

    report = _finish_cycle(planning, adapter, tmp_path)

    assert report.phase is Phase.RED
    assert "[x] adds\n[>] negative\n" in report.message


def _finish_cycle(service: TddService, adapter: FakeAdapter, root: Path) -> Report:
    adapter.outcome = Outcome.FAILED
    service.write_file(str(root), "test_calc", "def test_adds")
    adapter.outcome = Outcome.PASSED
    service.write_file(str(root), "calc.code", "impl")
    return _start(service, root)


def test_finishing_the_last_planned_test_returns_to_the_plan_phase(
    planning, adapter: FakeAdapter, tmp_path: Path
):
    _start(planning, tmp_path)
    planning.plan_tests(str(tmp_path), [ADDS])

    report = _finish_cycle(planning, adapter, tmp_path)

    assert report.phase is Phase.PLAN
    assert "every planned test is done" in report.message


def test_planning_more_tests_keeps_the_ones_already_done(
    planning, adapter: FakeAdapter, tmp_path: Path
):
    _start(planning, tmp_path)
    planning.plan_tests(str(tmp_path), [ADDS])
    _finish_cycle(planning, adapter, tmp_path)

    report = planning.plan_tests(str(tmp_path), [NEGATIVE])

    assert report.message.startswith("Test plan (1 of 2 done):\n[x] adds\n[>] negative")


def test_planning_no_more_tests_after_a_finished_plan_is_refused(
    planning, adapter: FakeAdapter, tmp_path: Path
):
    _start(planning, tmp_path)
    planning.plan_tests(str(tmp_path), [ADDS])
    _finish_cycle(planning, adapter, tmp_path)

    with pytest.raises(ValueError, match="at least one test"):
        planning.plan_tests(str(tmp_path), [])
    assert planning.status(str(tmp_path)).phase is Phase.PLAN


def test_a_write_ends_with_the_plan_and_the_next_step_of_its_new_phase(
    planning, adapter: FakeAdapter, tmp_path: Path
):
    _start(planning, tmp_path)
    planning.plan_tests(str(tmp_path), [ADDS])
    adapter.outcome = Outcome.FAILED

    report = planning.write_file(str(tmp_path), "test_calc", "def test_adds")

    assert report.message.endswith(Checklist([ADDS]).reminder(Phase.GREEN))


def test_status_ends_with_the_plan_and_its_next_step(planning, tmp_path: Path):
    _start(planning, tmp_path)
    planning.plan_tests(str(tmp_path), [ADDS])

    report = planning.status(str(tmp_path))

    assert report.message.endswith(Checklist([ADDS]).reminder(Phase.RED))


def test_rolling_back_a_planned_cycle_keeps_the_plan(
    adapter: FakeAdapter, tree: FakeTree, tmp_path: Path
):
    history = FakeHistory()
    planning = TddService(
        {"fake": adapter}, pending_changes=tree, history=history, require_plan=True
    )
    _start(planning, tmp_path)
    planning.plan_tests(str(tmp_path), [ADDS])
    adapter.outcome = Outcome.FAILED
    planning.write_file(str(tmp_path), "test_calc", "def test_adds")
    adapter.outcome = Outcome.PASSED

    report = planning.rollback_cycle(str(tmp_path))

    assert report.phase is Phase.RED
    assert report.message.endswith(Checklist([ADDS]).reminder(Phase.RED))


def test_a_red_test_not_named_after_the_planned_test_is_reverted(
    planning, adapter: FakeAdapter, tmp_path: Path
):
    _start(planning, tmp_path)
    planning.plan_tests(str(tmp_path), [ADDS, NEGATIVE])
    adapter.outcome = Outcome.FAILED

    report = planning.write_file(str(tmp_path), "test_calc", "def test_negative")

    assert report.phase is Phase.RED
    assert not (tmp_path / "test_calc").exists()
    assert "isn't the planned test 'adds'" in report.message


def test_a_planned_name_matches_ignoring_case_and_separators(
    planning, adapter: FakeAdapter, tmp_path: Path
):
    _start(planning, tmp_path)
    planning.plan_tests(
        str(tmp_path), [PlannedTest("adds two numbers", "-", "add 2 and 3", "5")]
    )
    adapter.outcome = Outcome.FAILED

    report = planning.write_file(str(tmp_path), "test_calc", 'it("Adds Two Numbers")')

    assert report.phase is Phase.GREEN


def test_a_planned_test_that_already_passes_is_checked_off(
    planning, adapter: FakeAdapter, tmp_path: Path
):
    _start(planning, tmp_path)
    planning.plan_tests(str(tmp_path), [ADDS, NEGATIVE])
    adapter.counts = SuiteCounts(tests=1, failures=0)

    report = planning.write_file(str(tmp_path), "test_calc", "def test_adds")

    assert report.phase is Phase.RED
    assert "[x] adds\n[>] negative\n" in report.message
    assert (
        "'adds' already passes, so it's checked off: commit it ('. t'), then "
        "call advance_tdd_phase."
    ) in report.message


def test_a_failing_green_write_under_a_plan_is_kept(
    planning, adapter: FakeAdapter, tmp_path: Path
):
    _start(planning, tmp_path)
    planning.plan_tests(str(tmp_path), [ADDS])
    adapter.outcome = Outcome.FAILED
    planning.write_file(str(tmp_path), "test_calc", "def test_adds")

    report = planning.write_file(str(tmp_path), "calc.code", "impl")

    assert report.phase is Phase.GREEN
    assert (tmp_path / "calc.code").exists()
