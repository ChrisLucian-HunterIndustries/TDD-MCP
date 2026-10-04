"""TypeScript (and JavaScript) support: vitest for running tests and coverage."""

from __future__ import annotations

import re
import tempfile
from dataclasses import replace
from pathlib import Path, PurePath

from tdd_mcp.cycle import FileKind, Outcome
from tdd_mcp.languages.base import Function, SuiteRun, run_suite
from tdd_mcp.reports import (
    count_junit,
    uncovered_from_istanbul,
    untaken_branches_from_istanbul,
)

CODE_SUFFIXES = frozenset(
    {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
)
TEST_DIRECTORIES = frozenset({"__tests__", "test", "tests"})
TEST_MARKERS = frozenset({"test", "spec"})
QUOTES = frozenset("'\"`")
DECLARATION = (
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\*?|class|const|let|var|interface|type|enum)\s+(\w+)"
)
FUNCTION_HEAD = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\*?\s+(\w+)"
    r"|(?:(?:public|private|protected|static|readonly|async|get|set)\s+)*"
    r"(?!(?:if|for|while|switch|catch|return|function)\b)(\w+)\s*\([^)]*\)\s*"
    r"(?::[^{;=]*)?\{)",
    re.MULTILINE,
)
NON_SPACE = re.compile(r"\S")
COMMENT_DIRECTIVES = (
    "/",
    "@ts-",
    "eslint-",
    "istanbul ",
    "c8 ",
    "v8 ",
    "prettier-ignore",
    "biome-ignore",
)
VITEST_ENTRY = Path("node_modules/vitest/vitest.mjs")
MISSING_VITEST = (
    f"vitest not found at {VITEST_ENTRY}. "
    "Install it in the project: npm install -D vitest @vitest/coverage-v8"
)
# vitest exits 1 for failing tests and for import or syntax errors alike.
VITEST_OUTCOMES = {0: Outcome.PASSED, 1: Outcome.FAILED}


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

    def comment_lines(self, source: str) -> frozenset[int]:
        return frozenset(self.uncommented(source))

    def uncommented(self, source: str) -> dict[int, str]:
        lines: dict[int, str] = {}
        i = 0
        while i < len(source):
            if source[i] in QUOTES:
                i = _string_end(source, i)
            elif source.startswith(("//", "/*"), i):
                end = _comment_end(source, i)
                if not source[i + 2 : end].lstrip().startswith(COMMENT_DIRECTIVES):
                    first = source.count("\n", 0, i) + 1
                    last = first + source.count("\n", i, end)
                    lines.update(dict.fromkeys(range(first + 1, last + 1), ""))
                    line_start = source.rfind("\n", 0, i) + 1
                    lines[first] = source[line_start:i].rstrip()
                i = end
            else:
                i += 1
        return lines

    def definitions(self, source: str) -> frozenset[str]:
        return frozenset(re.findall(DECLARATION, source, re.MULTILINE))

    def functions(self, source: str) -> tuple[Function, ...]:
        found = []
        for match in FUNCTION_HEAD.finditer(source):
            name = match.group(1) or match.group(2)
            opening = source.find("{", match.end(1) if match.group(1) else match.end(2))
            first = NON_SPACE.search(source, opening + 1)
            found.append(
                Function(
                    name,
                    start=_line(source, match.start()),
                    body=_line(source, first.start() if first else opening),
                    end=_line(source, _block_end(source, opening)),
                )
            )
        return tuple(found)

    def run_tests(
        self, root: Path, path: str | None = None, test_name: str | None = None
    ) -> SuiteRun:
        selection = [path] if path else []
        if test_name:
            selection += ["-t", test_name]
        return self._vitest(root, *selection)

    def run_coverage(self, root: Path) -> SuiteRun:
        # Reports go to a temp dir so coverage runs leave the working tree clean.
        with tempfile.TemporaryDirectory(prefix="tdd-mcp-coverage-") as report_dir:
            run = self._vitest(
                root,
                "--coverage.enabled",
                "--coverage.reporter=text",
                "--coverage.reporter=json",
                f"--coverage.reportsDirectory={report_dir}",
            )
            report = Path(report_dir) / "coverage-final.json"
            if not report.is_file():
                return run
            text = report.read_text(encoding="utf-8")
            return replace(
                run,
                uncovered=uncovered_from_istanbul(text, root),
                untaken=untaken_branches_from_istanbul(text, root),
            )

    def _vitest(self, root: Path, *args: str) -> SuiteRun:
        entry = root / VITEST_ENTRY
        # Node also exits 1 for a missing module, which would pass for a failing test.
        if not entry.is_file():
            return SuiteRun(Outcome.ERROR, MISSING_VITEST)
        with tempfile.TemporaryDirectory(prefix="tdd-mcp-junit-") as report_dir:
            junit = Path(report_dir) / "junit.xml"
            run = run_suite(
                [
                    "node",
                    str(entry),
                    "run",
                    "--passWithNoTests",
                    "--reporter=default",
                    "--reporter=junit",
                    f"--outputFile.junit={junit}",
                    *args,
                ],
                root,
                VITEST_OUTCOMES,
            )
            if not junit.is_file():
                return run
            return replace(run, counts=count_junit(junit.read_text(encoding="utf-8")))


def _string_end(source: str, start: int) -> int:
    quote, i = source[start], start + 1
    while i < len(source) and source[i] != quote:
        i += 2 if source[i] == "\\" else 1
    return i + 1


def _line(source: str, index: int) -> int:
    return source.count("\n", 0, index) + 1


def _block_end(source: str, opening: int) -> int:
    depth, i = 0, opening
    while i < len(source):
        if source[i] in QUOTES:
            i = _string_end(source, i)
            continue
        if source.startswith(("//", "/*"), i):
            i = _comment_end(source, i)
            continue
        depth += {"{": 1, "}": -1}.get(source[i], 0)
        if depth == 0:
            return i
        i += 1
    return len(source) - 1


def _comment_end(source: str, start: int) -> int:
    if source.startswith("//", start):
        end = source.find("\n", start)
        return len(source) if end == -1 else end
    end = source.find("*/", start + 2)
    return len(source) if end == -1 else end + 2
