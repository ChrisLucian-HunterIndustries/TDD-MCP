"""The contract each supported language implements, plus shared test-runner plumbing."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Protocol

from tdd_mcp.cycle import FileKind, Outcome
from tdd_mcp.reports import SuiteCounts

DEFAULT_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class SuiteRun:
    outcome: Outcome
    output: str
    counts: SuiteCounts | None = None
    # Root-relative POSIX path -> line numbers not executed; coverage runs only.
    uncovered: Mapping[str, frozenset[int]] = field(default_factory=dict)
    untaken: Mapping[str, frozenset[int]] = field(default_factory=dict)


@dataclass(frozen=True)
class Function:
    name: str
    start: int
    body: int
    end: int


class LanguageAdapter(Protocol):
    name: str

    def classify(self, relative_path: PurePath) -> FileKind:
        """Whether a path (relative to the project root) is a test, production code, or neither."""
        ...

    def comment_lines(self, source: str) -> frozenset[int]:
        """Line numbers holding a comment, other than tool directives such as `# noqa`."""
        ...

    def uncommented(self, source: str) -> dict[int, str]:
        """Each comment line (as in `comment_lines`) with its comment removed."""
        ...

    def definitions(self, source: str) -> frozenset[str]:
        """Names the source declares at its top level (classes, functions, constants)."""
        ...

    def functions(self, source: str) -> tuple[Function, ...]:
        """Functions and methods, with their first line, first statement and last line."""
        ...

    def run_tests(
        self, root: Path, path: str | None = None, test_name: str | None = None
    ) -> SuiteRun:
        """Run all tests without coverage, or only those under `path` and/or matching `test_name`."""
        ...

    def run_coverage(self, root: Path) -> SuiteRun: ...


def run_suite(
    command: Sequence[str],
    cwd: Path,
    exit_outcomes: Mapping[int, Outcome],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    env: Mapping[str, str] | None = None,
) -> SuiteRun:
    """Run a test command, mapping its exit code to an `Outcome` (unmapped codes are errors)."""
    try:
        result = subprocess.run(
            list(command),
            check=False,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env={**os.environ, **(env or {})},
        )
    except subprocess.TimeoutExpired:
        return SuiteRun(
            Outcome.ERROR,
            f"Test command timed out after {timeout} seconds. "
            "Look for a test or code path that never finishes.",
        )
    except OSError as e:
        return SuiteRun(
            Outcome.ERROR,
            f"Could not run test command: {e}. "
            "Ask the user to install the project's test runner.",
        )

    output = result.stdout + result.stderr
    outcome = exit_outcomes.get(result.returncode)
    if outcome is None:
        return SuiteRun(
            Outcome.ERROR,
            f"{output}\nUnexpected exit code {result.returncode}. "
            "Read the output above for the cause.",
        )
    return SuiteRun(outcome, output)
