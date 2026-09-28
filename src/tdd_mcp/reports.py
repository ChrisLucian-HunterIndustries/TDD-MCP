"""Reading test runners' machine-readable reports."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path


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


def uncovered_from_coverage_py(report: str, root: Path) -> dict[str, frozenset[int]]:
    """Missing lines per file from a coverage.py JSON report, keyed by root-relative POSIX path."""
    uncovered = {}
    for name, data in json.loads(report)["files"].items():
        if data["missing_lines"]:
            uncovered[_relative(name, root)] = frozenset(data["missing_lines"])
    return uncovered


def _relative(name: str, root: Path) -> str:
    path = Path(name)
    return (path.relative_to(root) if path.is_absolute() else path).as_posix()
