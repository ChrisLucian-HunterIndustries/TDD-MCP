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
