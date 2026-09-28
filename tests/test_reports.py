import json
from pathlib import Path

from tdd_mcp.reports import (
    SuiteCounts,
    count_junit,
    uncovered_from_coverage_py,
    uncovered_from_istanbul,
)

PYTEST_JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">
<testsuite name="pytest" errors="1" failures="1" skipped="2" tests="5">
<testcase classname="" name="test_err"><error message="collection failure"/></testcase>
</testsuite></testsuites>"""


def test_counts_tests_and_failures_including_errors():
    assert count_junit(PYTEST_JUNIT) == SuiteCounts(tests=5, failures=2)


def test_coverage_py_json_lists_missing_lines_by_root_relative_path(tmp_path: Path):
    report = json.dumps(
        {
            "files": {
                str(Path("src") / "calc.py"): {"missing_lines": [6, 7]},
                str(tmp_path / "other.py"): {"missing_lines": [2]},
                "test_calc.py": {"missing_lines": []},
            }
        }
    )
    assert uncovered_from_coverage_py(report, tmp_path) == {
        "src/calc.py": frozenset({6, 7}),
        "other.py": frozenset({2}),
    }


def test_coverage_py_json_counts_partial_branch_lines_as_uncovered(tmp_path: Path):
    report = json.dumps(
        {
            "files": {
                "calc.py": {"missing_lines": [9], "missing_branches": [[3, 5], [7, -1]]}
            }
        }
    )
    assert uncovered_from_coverage_py(report, tmp_path) == {
        "calc.py": frozenset({3, 7, 9})
    }


def test_istanbul_json_lists_lines_of_unexecuted_statements(tmp_path: Path):
    def statement(line: int) -> dict:
        return {"start": {"line": line, "column": 0}, "end": {"line": line}}

    report = json.dumps(
        {
            str(tmp_path / "src" / "calc.ts"): {
                "statementMap": {
                    "0": statement(1),
                    "1": statement(3),
                    "2": statement(4),
                },
                "s": {"0": 1, "1": 0, "2": 0},
            },
            str(tmp_path / "covered.ts"): {
                "statementMap": {"0": statement(1)},
                "s": {"0": 2},
            },
        }
    )
    assert uncovered_from_istanbul(report, tmp_path) == {
        "src/calc.ts": frozenset({3, 4})
    }
