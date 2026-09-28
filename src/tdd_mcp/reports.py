"""Reading test runners' machine-readable reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


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
        partial = {source for source, _ in data.get("missing_branches", [])}
        lines = frozenset(data["missing_lines"]) | partial
        if lines:
            uncovered[_relative(name, root)] = lines
    return uncovered


def uncovered_from_istanbul(report: str, root: Path) -> dict[str, frozenset[int]]:
    """Start lines of unexecuted statements and untaken branches per file from an istanbul JSON report."""
    uncovered = {}
    for name, data in json.loads(report).items():
        lines = frozenset(
            data["statementMap"][statement]["start"]["line"]
            for statement, hits in data["s"].items()
            if hits == 0
        ) | _untaken_branch_lines(data)
        if lines:
            uncovered[_relative(name, root)] = lines
    return uncovered


def _untaken_branch_lines(data: dict) -> frozenset[int]:
    lines = set()
    for branch, counts in data.get("b", {}).items():
        mapping = data["branchMap"][branch]
        for location, hits in zip(mapping["locations"], counts):
            if hits == 0:
                start = location["start"] or mapping["loc"]["start"]
                lines.add(start["line"])
    return frozenset(lines)


def _relative(name: str, root: Path) -> str:
    path = Path(name)
    return (path.relative_to(root) if path.is_absolute() else path).as_posix()
