"""Reading test runners' machine-readable reports."""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass


@dataclass(frozen=True)
class SuiteCounts:
    tests: int
    failures: int


def count_junit(xml: str) -> SuiteCounts:
    """Total tests, and failures plus errors, across a JUnit XML report's test suites."""
    suites = ElementTree.fromstring(xml).iter("testsuite")
    tests = failures = 0
    for suite in suites:
        tests += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    return SuiteCounts(tests=tests, failures=failures)
