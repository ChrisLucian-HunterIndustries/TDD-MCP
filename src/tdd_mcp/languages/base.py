"""The contract each supported language implements, plus shared test-runner plumbing."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Protocol

from tdd_mcp.cycle import FileKind, Outcome

DEFAULT_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class SuiteRun:
    outcome: Outcome
    output: str


class LanguageAdapter(Protocol):
    name: str

    def classify(self, relative_path: PurePath) -> FileKind:
        """Whether a path (relative to the project root) is a test, production code, or neither."""
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
            Outcome.ERROR, f"Test command timed out after {timeout} seconds"
        )
    except OSError as e:
        return SuiteRun(Outcome.ERROR, f"Could not run test command: {e}")

    output = result.stdout + result.stderr
    outcome = exit_outcomes.get(result.returncode)
    if outcome is None:
        return SuiteRun(
            Outcome.ERROR, f"{output}\nUnexpected exit code {result.returncode}"
        )
    return SuiteRun(outcome, output)
