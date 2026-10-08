import os
import sys
from pathlib import Path, PurePath

import pytest

from tdd_mcp.cycle import FileKind, Outcome
from tdd_mcp.languages import ADAPTERS
from tdd_mcp.languages.python import PythonAdapter, python_for

adapter = PythonAdapter()


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("test_a.py", FileKind.TEST),
        ("pkg/a_test.py", FileKind.TEST),
        ("conftest.py", FileKind.TEST),
        ("tests/helpers.py", FileKind.TEST),
        ("src/pkg/test/helpers.py", FileKind.TEST),
        ("a.py", FileKind.PRODUCTION),
        ("src/pkg/testing.py", FileKind.PRODUCTION),
        ("src/pkg/contest.py", FileKind.PRODUCTION),
        ("stub.pyi", FileKind.PRODUCTION),
        ("README.md", FileKind.OTHER),
        ("tests/data.json", FileKind.OTHER),
        ("pyproject.toml", FileKind.OTHER),
    ],
)
def test_classify(path: str, kind: FileKind):
    assert adapter.classify(PurePath(path)) is kind


def test_registered_as_python():
    assert ADAPTERS["python"].name == "python"


def test_comment_lines_ignore_hashes_inside_strings():
    source = "x = 1  # why\ns = '# not a comment'\n# full line\n"
    assert adapter.comment_lines(source) == frozenset({1, 3})


def test_uncommented_gives_each_comment_line_without_its_comment():
    source = "x = 1  # why\ns = '# no'\n# full line\nif x:  # noqa\n    pass\n"
    assert adapter.uncommented(source) == {1: "x = 1", 3: ""}


def test_comment_lines_skip_tool_directives():
    source = (
        "#!/usr/bin/env python\n"
        "import os  # noqa: F401\n"
        "x = f()  # type: ignore\n"
        "if x:  # pragma: no cover\n"
        "    pass\n"
        "# a real comment\n"
    )
    assert adapter.comment_lines(source) == frozenset({6})


def test_definitions_are_the_top_level_classes_and_functions():
    source = (
        "class Game:\n"
        "    def move(self):\n"
        "        pass\n"
        "def helper():\n"
        "    pass\n"
        "async def fetch():\n"
        "    pass\n"
        "x = 'def not_one():'\n"
    )
    assert adapter.definitions(source) == frozenset({"Game", "helper", "fetch"})


def test_functions_span_from_decorator_to_last_line_with_their_first_statement():
    from tdd_mcp.languages.base import Function

    source = (
        "class Game:\n"
        "    def __init__(self):\n"
        "        self.board = []\n"
        "\n"
        "    @property\n"
        "    def size(self):\n"
        '        """Doc."""\n'
        "        return 3\n"
        "def helper():\n"
        "    pass\n"
    )
    assert adapter.functions(source) == (
        Function("__init__", start=2, body=3, end=3),
        Function("size", start=5, body=8, end=8),
        Function("helper", start=9, body=10, end=10),
    )


def test_python_for_falls_back_to_current_interpreter(tmp_path: Path):
    assert python_for(tmp_path) == sys.executable


@pytest.mark.parametrize("relative", [".venv/Scripts/python.exe", ".venv/bin/python"])
def test_python_for_prefers_project_venv(tmp_path: Path, relative: str):
    interpreter = tmp_path / relative
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    assert python_for(tmp_path) == str(interpreter)


def _project(tmp_path: Path, test_body: str) -> Path:
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_calc.py").write_text(
        f"from calc import *\n\n\ndef test_it():\n    {test_body}\n"
    )
    return tmp_path


def test_passing_suite(tmp_path: Path):
    run = adapter.run_tests(_project(tmp_path, "assert add(1, 2) == 3"))
    assert run.outcome is Outcome.PASSED


def test_failing_suite(tmp_path: Path):
    run = adapter.run_tests(_project(tmp_path, "assert add(1, 2) == 4"))
    assert run.outcome is Outcome.FAILED
    assert "assert 3 == 4" in run.output


def test_non_ascii_output_survives(tmp_path: Path):
    (tmp_path / "test_calc.py").write_text(
        "def test_it():\n    assert '\u2713' == 'x'\n", encoding="utf-8"
    )
    assert "\u2713" in adapter.run_tests(tmp_path).output


def test_import_error_counts_as_failing(tmp_path: Path):
    project = _project(tmp_path, "pass")
    (project / "test_calc.py").write_text("from calc import subtract\n")
    assert adapter.run_tests(project).outcome is Outcome.FAILED


def test_empty_suite_passes(tmp_path: Path):
    assert adapter.run_tests(tmp_path).outcome is Outcome.PASSED


def _two_test_files(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_good.py").write_text(
        "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n"
    )
    (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert False\n")
    return tmp_path


def test_pytest_output_is_quiet_with_short_tracebacks(tmp_path: Path):
    """Every reply carries the test output; headers and whole test bodies cost tokens."""
    (tmp_path / "test_a.py").write_text(
        "def test_fails():\n    marker = 1\n    assert marker == 2\n"
    )

    output = adapter.run_tests(tmp_path).output

    assert "test session starts" not in output
    assert "marker = 1" not in output
    assert "test_fails" in output


def test_coverage_report_skips_fully_covered_files(tmp_path: Path):
    """A row per fully covered file buries the one that needs attention."""
    (tmp_path / "done.py").write_text("def one():\n    return 1\n")
    (tmp_path / "partial.py").write_text(
        "def two(x):\n    if x:\n        return 2\n    return 0\n"
    )
    (tmp_path / "test_a.py").write_text(
        "from done import one\nfrom partial import two\n\n\n"
        "def test_both():\n    assert one() == 1\n    assert two(1) == 2\n"
    )

    output = adapter.run_coverage(tmp_path).output

    assert "partial.py" in output
    assert "done.py" not in output


def test_run_tests_in_one_file(tmp_path: Path):
    run = adapter.run_tests(_two_test_files(tmp_path), path="tests/test_good.py")
    assert run.outcome is Outcome.PASSED
    assert "2 passed" in run.output


def test_run_reports_test_and_failure_counts(tmp_path: Path):
    run = adapter.run_tests(_two_test_files(tmp_path))
    assert (run.counts.tests, run.counts.failures) == (3, 1)


def test_unimportable_test_file_counts_each_of_its_tests(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from calc import add, sub\n\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n\n\n"
        "def test_sub():\n    assert sub(3, 2) == 1\n"
    )
    run = adapter.run_tests(tmp_path)
    assert (run.counts.tests, run.counts.failures) == (2, 2)


def test_test_file_with_syntax_error_counts_as_one_failing_test(tmp_path: Path):
    (tmp_path / "test_calc.py").write_text("def test_add(:\n    pass\n")
    run = adapter.run_tests(tmp_path)
    assert (run.counts.tests, run.counts.failures) == (1, 1)


def test_unimportable_test_file_in_a_dotted_folder_counts_as_one_failing_test(
    tmp_path: Path,
):
    """pytest's JUnit name `v1.2.test_calc` doesn't map back to `v1.2/test_calc.py`."""
    (tmp_path / "v1.2").mkdir()
    (tmp_path / "v1.2" / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    run = adapter.run_tests(tmp_path)
    assert (run.counts.tests, run.counts.failures) == (1, 1)


def test_unstartable_interpreter_is_an_error_without_counts(tmp_path: Path):
    for relative in (".venv/Scripts/python.exe", ".venv/bin/python"):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text("not an executable")
    run = adapter.run_tests(tmp_path)
    assert run.outcome is Outcome.ERROR
    assert run.counts is None


def test_run_tests_in_one_folder(tmp_path: Path):
    run = adapter.run_tests(_two_test_files(tmp_path), path="tests")
    assert run.outcome is Outcome.PASSED
    assert "2 passed" in run.output


def test_run_single_test_by_name(tmp_path: Path):
    run = adapter.run_tests(_two_test_files(tmp_path), test_name="test_two")
    assert run.outcome is Outcome.PASSED
    assert "1 passed" in run.output


def test_run_single_test_in_file(tmp_path: Path):
    project = _two_test_files(tmp_path)
    run = adapter.run_tests(project, path="test_bad.py", test_name="test_bad")
    assert run.outcome is Outcome.FAILED
    assert "1 failed" in run.output


def test_never_runs_stale_bytecode(tmp_path: Path):
    """Python trusts cached bytecode when source mtime and size are unchanged, as after a quick revert."""
    project = _project(tmp_path, "assert add(2, 2) == 4")
    source = project / "calc.py"
    source.write_text("def add(a, b):\n    return a * b\n")
    stat = source.stat()
    assert adapter.run_tests(project).outcome is Outcome.PASSED

    source.write_text("def add(a, b):\n    return a - b\n")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    assert adapter.run_tests(project).outcome is Outcome.FAILED
    assert not (project / "__pycache__").exists()


def test_coverage_reports_missing_lines(tmp_path: Path):
    project = _project(tmp_path, "assert add(1, 2) == 3")
    (project / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef unused():\n    return 0\n"
    )
    run = adapter.run_coverage(project)
    assert run.outcome is Outcome.PASSED
    assert "Missing" in run.output
    assert "calc.py" in run.output


def test_coverage_leaves_no_data_file_in_the_project(tmp_path: Path):
    adapter.run_coverage(_project(tmp_path, "assert add(1, 2) == 3"))
    assert not list(tmp_path.glob(".coverage*"))


def test_coverage_reports_uncovered_lines_by_file(tmp_path: Path):
    project = _project(tmp_path, "assert add(1, 2) == 3")
    (project / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef unused():\n    return 0\n"
    )
    assert adapter.run_coverage(project).uncovered["calc.py"] == frozenset({6})


def test_coverage_reports_lines_with_untaken_branches(tmp_path: Path):
    project = _project(tmp_path, "assert add(1, 2) == 3")
    (project / "calc.py").write_text(
        "def add(a, b):\n    if a > 0:\n        b += 0\n    return a + b\n"
    )
    assert adapter.run_coverage(project).uncovered["calc.py"] == frozenset({2})


def test_coverage_reports_untaken_branches_apart_from_unrun_lines(tmp_path: Path):
    project = _project(tmp_path, "assert add(1, 2) == 3")
    (project / "calc.py").write_text(
        "def add(a, b):\n    if a < 0:\n        b += 0\n    return a + b\n"
    )
    assert adapter.run_coverage(project).untaken == {"calc.py": frozenset({2})}
