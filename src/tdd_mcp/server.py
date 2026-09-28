"""MCP server that enforces the red/green/refactor test-driven development cycle."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from tdd_mcp import git_gate
from tdd_mcp.languages import ADAPTERS, LanguageName
from tdd_mcp.service import TddService

# Comma-separated fnmatch patterns of project paths that skip the TDD cycle.
EXEMPT_ENV_VAR = "TDD_MCP_EXEMPT"

mcp = MCPServer(
    "test-driven-development",
    instructions=(
        "Enforces the test-driven development cycle when writing code files. "
        "Write every code file through this server's `write_file` or "
        "`edit_file` tools, never with other editing tools. Each cycle: "
        "(1) call `run_coverage` — all tests must pass, and the coverage "
        "report shows what is untested; (2) write exactly one new failing "
        "test (production code is locked until exactly one test fails, and "
        "adding more than one test keeps you in red); "
        "(3) write production code until the tests pass (tests are locked "
        "meanwhile); (4) refactor test or production code — any edit that "
        "breaks the tests or adds a test is automatically reverted; then call "
        "`run_coverage` to start the next cycle, which also requires every "
        "production line changed this cycle to be covered, so don't write code "
        "for tests that don't exist yet. Call `tdd_status` any time "
        "to see the current phase and what is allowed. To iterate faster, "
        "`run_tests` runs all tests, a file or folder, or a single test "
        "without coverage; it never advances the phase. Non-code files (docs, "
        "config) can be written in any phase and don't run the tests. Neither "
        "do paths matching the server's `TDD_MCP_EXEMPT` patterns. Every edit "
        "requires a clean git working tree: commit each step first (e.g. "
        "'. t' for a new failing test, then '^ f' for the code that passes it)."
    ),
)


def new_service() -> TddService:
    raw = os.environ.get(EXEMPT_ENV_VAR, "")
    return TddService(
        ADAPTERS,
        pending_changes=git_gate.uncommitted_changes,
        history=git_gate,
        exempt=[p.strip() for p in raw.split(",") if p.strip()],
    )


service = new_service()


@contextmanager
def _refusals_as_tool_errors() -> Iterator[None]:
    # MCPServer hides the text of any exception that isn't a ToolError.
    try:
        yield
    except ValueError as e:
        raise ToolError(str(e)) from e


@mcp.tool()
def tdd_status(location: str) -> str:
    """Show the current TDD phase for a project and what may be written in it.

    Args:
        location: Path to the project root.
    """
    with _refusals_as_tool_errors():
        return service.status(location).render()


@mcp.tool()
def run_coverage(location: str, language: LanguageName = "python") -> str:
    """Run the full test suite with coverage. Starts each TDD cycle.

    If every test passes, the cycle moves to the red phase, where a failing
    test must be written before production code can change.

    Args:
        location: Path to the project root.
        language: The project's language, which decides how tests are run.
    """
    with _refusals_as_tool_errors():
        return service.run_coverage(location, language).render()


@mcp.tool()
def run_tests(
    location: str, path: str | None = None, test_name: str | None = None
) -> str:
    """Run tests without coverage: faster, for iterating. Never changes the TDD phase.

    Use this to check progress while writing a test or code. Only `run_coverage`
    and the test runs that `write_file`/`edit_file` trigger advance the cycle, so
    a passing or failing result here unlocks nothing.

    Runs the whole suite by default. Narrow it with `path` (a test file or
    folder) and/or `test_name` (matched against test names: pytest `-k`,
    vitest `-t`) to run all tests in a file or folder, or a single test.
    Requires a cycle started with `run_coverage`.

    Args:
        location: Path to the project root.
        path: Test file or folder, relative to `location` (or absolute, inside it).
        test_name: Name, or part of a name, of the test(s) to run.
    """
    with _refusals_as_tool_errors():
        return service.run_tests(location, path, test_name).render()


@mcp.tool()
def write_file(location: str, path: str, content: str) -> str:
    """Create or overwrite a file, if the current TDD phase allows it, then run the tests.

    Test files may be written in the red and refactor phases; production
    files in the green and refactor phases. The test results decide the
    next phase.

    Args:
        location: Path to the project root.
        path: File path, relative to `location` (or absolute, inside it).
        content: The complete new file content.
    """
    with _refusals_as_tool_errors():
        return service.write_file(location, path, content).render()


@mcp.tool()
def edit_file(location: str, path: str, old_string: str, new_string: str) -> str:
    """Replace exactly one occurrence of `old_string` in a file, if the TDD phase allows it.

    Same phase rules and test run as `write_file`.

    Args:
        location: Path to the project root.
        path: File path, relative to `location` (or absolute, inside it).
        old_string: Exact text to replace; must occur exactly once in the file.
        new_string: Replacement text.
    """
    with _refusals_as_tool_errors():
        return service.edit_file(location, path, old_string, new_string).render()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
