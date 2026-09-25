"""TypeScript (and JavaScript) support: vitest for running tests and coverage."""

from __future__ import annotations

from pathlib import PurePath

from tdd_mcp.cycle import FileKind

CODE_SUFFIXES = frozenset(
    {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
)
TEST_DIRECTORIES = frozenset({"__tests__", "test", "tests"})
TEST_MARKERS = frozenset({"test", "spec"})


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
