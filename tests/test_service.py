from pathlib import Path, PurePath

import pytest

from tdd_mcp.cycle import FileKind, Outcome, Phase
from tdd_mcp.languages.base import SuiteRun
from tdd_mcp.service import Report, TddError, TddService
from tdd_mcp.workspace import WorkspaceError


class FakeAdapter:
    """A made-up language: `test*` files are tests, `*.code` files are production."""

    name = "fake"

    def __init__(self) -> None:
        self.outcome = Outcome.PASSED
        self.test_runs = 0

    def classify(self, relative_path: PurePath) -> FileKind:
        if relative_path.name.startswith("test"):
            return FileKind.TEST
        if relative_path.suffix == ".code":
            return FileKind.PRODUCTION
        return FileKind.OTHER

    def run_tests(self, root: Path) -> SuiteRun:
        self.test_runs += 1
        return SuiteRun(self.outcome, "test output")

    def run_coverage(self, root: Path) -> SuiteRun:
        return SuiteRun(self.outcome, "coverage output")


@pytest.fixture
def adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture
def service(adapter: FakeAdapter) -> TddService:
    return TddService({"fake": adapter})


def _start(service: TddService, root: Path) -> Report:
    return service.run_coverage(str(root), "fake")


def test_status_before_coverage_requires_coverage(service: TddService, tmp_path: Path):
    report = service.status(str(tmp_path))
    assert report.phase is Phase.COVERAGE_REQUIRED
    assert "coverage" in report.message


def test_writing_before_coverage_is_refused(service: TddService, tmp_path: Path):
    with pytest.raises(TddError, match="run_coverage"):
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


def test_passing_new_test_stays_red_and_keeps_file(service, tmp_path: Path):
    _start(service, tmp_path)
    report = service.write_file(str(tmp_path), "test_calc", "test")
    assert report.phase is Phase.RED
    assert "fails" in report.message
    assert (tmp_path / "test_calc").read_text() == "test"


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
def test_exempt_paths_skip_the_cycle(adapter: FakeAdapter, tmp_path: Path, path: str):
    service = TddService({"fake": adapter}, exempt=("scripts/*",))
    _start(service, tmp_path)

    report = service.write_file(str(tmp_path), path, "x")

    assert report.phase is Phase.RED
    assert "exempt" in report.message
    assert (tmp_path / path).read_text() == "x"
    assert adapter.test_runs == 0


def test_exempt_patterns_do_not_match_other_paths(adapter: FakeAdapter, tmp_path: Path):
    service = TddService({"fake": adapter}, exempt=("scripts/*",))
    _start(service, tmp_path)
    with pytest.raises(TddError, match="not allowed in the red phase"):
        service.write_file(str(tmp_path), "src/calc.code", "x")


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
