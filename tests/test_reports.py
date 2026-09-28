import json
from pathlib import Path

from tdd_mcp.reports import SuiteCounts, count_junit, uncovered_from_coverage_py

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
