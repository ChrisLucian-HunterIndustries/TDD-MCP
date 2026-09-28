from tdd_mcp.reports import SuiteCounts, count_junit

PYTEST_JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">
<testsuite name="pytest" errors="1" failures="1" skipped="2" tests="5">
<testcase classname="" name="test_err"><error message="collection failure"/></testcase>
</testsuite></testsuites>"""


def test_counts_tests_and_failures_including_errors():
    assert count_junit(PYTEST_JUNIT) == SuiteCounts(tests=5, failures=2)
