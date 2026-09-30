from pathlib import Path, PurePath

import pytest

from tdd_mcp.cycle import FileKind, Outcome, Phase
from tdd_mcp.languages.base import SuiteRun
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
        self.test_runs = 0
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

    def run_tests(
        self, root: Path, path: str | None = None, test_name: str | None = None
    ) -> SuiteRun:
        self.test_runs += 1
        self.selections.append((path, test_name))
        return SuiteRun(self.outcome, "test output", self.counts)

    def run_coverage(self, root: Path) -> SuiteRun:
        return SuiteRun(self.outcome, "coverage output", self.counts, self.uncovered)


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


class FakeHistory:
    def __init__(self) -> None:
        self.head = "base"
        self.changed: dict[str, frozenset[int]] = {}
        self.ancestor = True

    def head_commit(self, root: Path) -> str:
        return self.head

    def is_ancestor(self, root: Path, commit: str) -> bool:
        return self.ancestor

    def changed_lines(self, root: Path, base: str) -> dict[str, frozenset[int]]:
        assert base == "base"
        return self.changed


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
