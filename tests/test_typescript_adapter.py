import shutil
import subprocess
from pathlib import Path, PurePath

import pytest

from tdd_mcp.cycle import FileKind, Outcome
from tdd_mcp.languages import ADAPTERS
from tdd_mcp.languages.typescript import TypeScriptAdapter

adapter = TypeScriptAdapter()
NPM = shutil.which("npm")
FIXTURE_FILES = frozenset({"node_modules", "package.json", "package-lock.json"})


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("src/calc.test.ts", FileKind.TEST),
        ("src/calc.spec.tsx", FileKind.TEST),
        ("calc.test.mts", FileKind.TEST),
        ("src/__tests__/calc.ts", FileKind.TEST),
        ("test/helpers.ts", FileKind.TEST),
        ("tests/setup.js", FileKind.TEST),
        ("src/calc.ts", FileKind.PRODUCTION),
        ("src/App.tsx", FileKind.PRODUCTION),
        ("src/types.d.ts", FileKind.PRODUCTION),
        ("src/testing.ts", FileKind.PRODUCTION),
        ("src/latest.ts", FileKind.PRODUCTION),
        ("index.js", FileKind.PRODUCTION),
        ("lib/util.cjs", FileKind.PRODUCTION),
        ("vitest.config.ts", FileKind.PRODUCTION),
        ("package.json", FileKind.OTHER),
        ("tsconfig.json", FileKind.OTHER),
        ("README.md", FileKind.OTHER),
        ("src/calc.py", FileKind.OTHER),
    ],
)
def test_classify(path: str, kind: FileKind):
    assert adapter.classify(PurePath(path)) is kind


def test_name():
    assert adapter.name == "typescript"


def test_registered_as_typescript():
    assert isinstance(ADAPTERS["typescript"], TypeScriptAdapter)


@pytest.mark.parametrize("run", [adapter.run_tests, adapter.run_coverage])
def test_missing_vitest_is_an_error_not_a_failing_test(tmp_path: Path, run):
    result = run(tmp_path)
    assert result.outcome is Outcome.ERROR
    assert "npm install -D vitest @vitest/coverage-v8" in result.output


@pytest.fixture(scope="module")
def installed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if NPM is None:
        pytest.skip("npm is not installed")
    root = tmp_path_factory.mktemp("typescript-project")
    (root / "package.json").write_text(
        '{"name": "fixture", "private": true, "type": "module"}'
    )
    subprocess.run(
        [NPM, "install", "--no-audit", "--no-fund", "-D"]
        + ["vitest@5", "@vitest/coverage-v8@5"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return root


@pytest.fixture
def project(installed: Path) -> Path:
    for entry in installed.iterdir():
        if entry.name not in FIXTURE_FILES:
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    (installed / "calc.ts").write_text(
        "export const add = (a: number, b: number) => a + b;\n\n"
        "export const unused = () => 0;\n"
    )
    return installed


def _write_test(
    project: Path, body: str, source: str = "./calc", name: str = "add"
) -> None:
    (project / "calc.test.ts").write_text(
        'import { expect, test } from "vitest";\n'
        f'import {{ add }} from "{source}";\n\n'
        f'test("{name}", () => {{\n  {body}\n}});\n',
        encoding="utf-8",
    )


def test_passing_suite(project: Path):
    _write_test(project, "expect(add(1, 2)).toBe(3);")
    assert adapter.run_tests(project).outcome is Outcome.PASSED


def test_failing_suite(project: Path):
    _write_test(project, "expect(add(1, 2)).toBe(4);", name="adds \u2713")
    run = adapter.run_tests(project)
    assert run.outcome is Outcome.FAILED
    assert "expected 3 to be 4" in run.output
    assert "adds \u2713" in run.output


def test_missing_module_counts_as_failing(project: Path):
    _write_test(project, "expect(add(1, 2)).toBe(3);", source="./nope")
    assert adapter.run_tests(project).outcome is Outcome.FAILED


def test_empty_suite_passes(project: Path):
    assert adapter.run_tests(project).outcome is Outcome.PASSED


def _two_test_files(project: Path) -> Path:
    (project / "tests").mkdir()
    (project / "tests" / "good.test.ts").write_text(
        'import { test } from "vitest";\n\n'
        'test("one", () => {});\ntest("two", () => {});\n'
    )
    (project / "bad.test.ts").write_text(
        'import { expect, test } from "vitest";\n\n'
        'test("bad", () => { expect(1).toBe(2); });\n'
    )
    return project


def test_run_tests_in_one_file(project: Path):
    run = adapter.run_tests(_two_test_files(project), path="tests/good.test.ts")
    assert run.outcome is Outcome.PASSED
    assert "2 passed" in run.output


def test_run_tests_in_one_folder(project: Path):
    run = adapter.run_tests(_two_test_files(project), path="tests")
    assert run.outcome is Outcome.PASSED
    assert "2 passed" in run.output


def test_run_single_test_by_name(project: Path):
    run = adapter.run_tests(_two_test_files(project), test_name="two")
    assert run.outcome is Outcome.PASSED
    assert "1 passed" in run.output


def test_run_single_test_in_file(project: Path):
    run = adapter.run_tests(
        _two_test_files(project), path="bad.test.ts", test_name="bad"
    )
    assert run.outcome is Outcome.FAILED
    assert "1 failed" in run.output


def test_run_reports_test_and_failure_counts(project: Path):
    run = adapter.run_tests(_two_test_files(project))
    assert (run.counts.tests, run.counts.failures) == (3, 1)


def test_runner_that_writes_no_report_has_no_counts(tmp_path: Path):
    fake = tmp_path / "node_modules" / "vitest" / "vitest.mjs"
    fake.parent.mkdir(parents=True)
    fake.write_text("process.exit(0);\n")
    run = adapter.run_tests(tmp_path)
    assert run.outcome is Outcome.PASSED
    assert run.counts is None


def test_coverage_reports_uncovered_lines_without_writing_reports(project: Path):
    _write_test(project, "expect(add(1, 2)).toBe(3);")
    run = adapter.run_coverage(project)
    assert run.outcome is Outcome.PASSED
    assert "Uncovered Line" in run.output
    assert "calc.ts" in run.output
    assert not (project / "coverage").exists()


def test_coverage_reports_uncovered_lines_by_file(project: Path):
    _write_test(project, "expect(add(1, 2)).toBe(3);")
    assert adapter.run_coverage(project).uncovered["calc.ts"] == frozenset({3})
