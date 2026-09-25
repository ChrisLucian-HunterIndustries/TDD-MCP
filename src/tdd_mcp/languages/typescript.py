"""TypeScript (and JavaScript) support: vitest for running tests and coverage."""

from __future__ import annotations

from pathlib import Path, PurePath

from tdd_mcp.cycle import FileKind, Outcome
from tdd_mcp.languages.base import SuiteRun

CODE_SUFFIXES = frozenset(
    {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
)
TEST_DIRECTORIES = frozenset({"__tests__", "test", "tests"})
TEST_MARKERS = frozenset({"test", "spec"})
VITEST_ENTRY = Path("node_modules/vitest/vitest.mjs")
MISSING_VITEST = (
    f"vitest not found at {VITEST_ENTRY}. "
    "Install it in the project: npm install -D vitest @vitest/coverage-v8"
)


class TypeScriptAdapter:
    name = "typescript"

    def classify(self, relative_path: PurePath) -> FileKind:
        if relative_path.suffix not in CODE_SUFFIXES:
            return FileKind.OTHER
        # e.g. "calc.test.ts" -> {"test"}; "types.d.ts" -> {"d"}
        inner_suffixes = set(relative_path.name.split(".")[1:-1])
        in_test_directory = not TEST_DIRECTORIES.isdisjoint(relative_path.parent.parts)
        is_test = in_test_directory or not TEST_MARKERS.isdisjoint(inner_suffixes)
        return FileKind.TEST if is_test else FileKind.PRODUCTION

    def run_tests(self, root: Path) -> SuiteRun:
        return self._vitest(root)

    def run_coverage(self, root: Path) -> SuiteRun:
        return self._vitest(root)

    def _vitest(self, root: Path) -> SuiteRun:
        # Node also exits 1 for a missing module, which would pass for a failing test.
        if not (root / VITEST_ENTRY).is_file():
            return SuiteRun(Outcome.ERROR, MISSING_VITEST)
        raise NotImplementedError
