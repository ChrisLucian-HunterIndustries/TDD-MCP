"""Python support: pytest for running tests, pytest-cov for coverage."""

from __future__ import annotations

import ast
import sys
import tempfile
from dataclasses import replace
from pathlib import Path, PurePath
from xml.etree import ElementTree

from tdd_mcp.cycle import FileKind, Outcome
from tdd_mcp.languages.base import SuiteRun, run_suite
from tdd_mcp.reports import SuiteCounts, count_junit, uncovered_from_coverage_py

CODE_SUFFIXES = frozenset({".py", ".pyi"})
TEST_DIRECTORIES = frozenset({"test", "tests"})
VENV_INTERPRETERS = (".venv/Scripts/python.exe", ".venv/bin/python")

# pytest exit codes: 2 is a collection error (e.g. importing a function that
# doesn't exist yet), which is a legitimate "red"; 5 means no tests collected.
PYTEST_OUTCOMES = {
    0: Outcome.PASSED,
    1: Outcome.FAILED,
    2: Outcome.FAILED,
    5: Outcome.PASSED,
}


def python_for(root: Path) -> str:
    """The project's own virtualenv interpreter if it has one, else the current interpreter."""
    for relative in VENV_INTERPRETERS:
        candidate = root / relative
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def count_pytest_junit(xml: str, root: Path) -> SuiteCounts:
    """JUnit counts, with an unimportable test file counted as the tests it defines.

    pytest reports a test file that fails to import as a single errored entry,
    which would hide how many tests the file adds.
    """
    counts = count_junit(xml)
    hidden = 0
    for case in ElementTree.fromstring(xml).iter("testcase"):
        error = case.find("error")
        if error is None or error.get("message") != "collection failure":
            continue
        module = ".".join(
            part for part in (case.get("classname"), case.get("name")) if part
        )
        hidden += _defined_tests(root / (module.replace(".", "/") + ".py")) - 1
    return SuiteCounts(counts.tests + hidden, counts.failures + hidden)


def _defined_tests(path: Path) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return 1
    return sum(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test")
        for node in ast.walk(tree)
    )


class PythonAdapter:
    name = "python"

    def classify(self, relative_path: PurePath) -> FileKind:
        if relative_path.suffix not in CODE_SUFFIXES:
            return FileKind.OTHER
        is_test = (
            relative_path.name.startswith("test_")
            or relative_path.stem.endswith("_test")
            or relative_path.name == "conftest.py"
            or not TEST_DIRECTORIES.isdisjoint(relative_path.parent.parts)
        )
        return FileKind.TEST if is_test else FileKind.PRODUCTION

    def run_tests(
        self, root: Path, path: str | None = None, test_name: str | None = None
    ) -> SuiteRun:
        selection = [path] if path else []
        if test_name:
            selection += ["-k", test_name]
        return self._pytest(root, *selection)

    def run_coverage(self, root: Path) -> SuiteRun:
        # Keep coverage's data and reports out of the project so the working tree stays clean.
        with tempfile.TemporaryDirectory(prefix="tdd-mcp-coverage-") as data_dir:
            report = Path(data_dir) / "coverage.json"
            run = self._pytest(
                root,
                "--cov",
                "--cov-branch",
                "--cov-report=term-missing",
                f"--cov-report=json:{report}",
                extra_env={"COVERAGE_FILE": str(Path(data_dir) / ".coverage")},
            )
            if not report.is_file():
                return run
            uncovered = uncovered_from_coverage_py(
                report.read_text(encoding="utf-8"), root
            )
            return replace(run, uncovered=uncovered)

    def _pytest(
        self, root: Path, *args: str, extra_env: dict[str, str] | None = None
    ) -> SuiteRun:
        with tempfile.TemporaryDirectory(prefix="tdd-mcp-junit-") as report_dir:
            junit = Path(report_dir) / "junit.xml"
            # .pyc validation uses whole-second mtime and size, so caching bytecode
            # could run stale code after a quick same-size edit or revert.
            run = run_suite(
                [
                    python_for(root),
                    "-m",
                    "pytest",
                    # Otherwise one import error hides every other test from the count.
                    "--continue-on-collection-errors",
                    f"--junitxml={junit}",
                    *args,
                ],
                root,
                PYTEST_OUTCOMES,
                env={
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONIOENCODING": "utf-8",
                    **(extra_env or {}),
                },
            )
            if not junit.is_file():
                return run
            counts = count_pytest_junit(junit.read_text(encoding="utf-8"), root)
            return replace(run, counts=counts)
