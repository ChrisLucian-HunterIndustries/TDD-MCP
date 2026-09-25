"""Python support: pytest for running tests, pytest-cov for coverage."""

from __future__ import annotations

import sys
from pathlib import Path, PurePath

from tdd_mcp.cycle import FileKind, Outcome
from tdd_mcp.languages.base import SuiteRun, run_suite

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

    def run_tests(self, root: Path) -> SuiteRun:
        return self._pytest(root)

    def run_coverage(self, root: Path) -> SuiteRun:
        return self._pytest(root, "--cov", "--cov-report=term-missing")

    def _pytest(self, root: Path, *args: str) -> SuiteRun:
        # .pyc validation uses whole-second mtime and size, so caching bytecode
        # could run stale code after a quick same-size edit or revert.
        return run_suite(
            [python_for(root), "-m", "pytest", *args],
            root,
            PYTEST_OUTCOMES,
            env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"},
        )
