"""MCP server that enforces the red/green/refactor test-driven development cycle."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from typing_extensions import TypedDict

from tdd_mcp import git_gate
from tdd_mcp.languages import ADAPTERS, LanguageName
from tdd_mcp.plan import planned_test_from
from tdd_mcp.service import TddService

# Comma-separated fnmatch patterns of project paths that skip the TDD cycle.
EXEMPT_ENV_VAR = "TDD_MCP_EXEMPT"

mcp = MCPServer(
    "test-driven-development",
    instructions=(
        "Enforces test-driven development. Change code files only with this "
        "server's `write_file` and `edit_file`. Each reply starts with "
        "'Phase: <phase>' and ends with the next step: do that step and nothing "
        "more.\n"
        "1. plan: call `plan_tests` with every test the task needs, each with a "
        "name, arrange, act and assert.\n"
        "2. red: write ONE failing test; a test that imports code that doesn't "
        "exist yet counts as failing. Commit it as '. t'.\n"
        "3. green: write the simplest production code that makes every test "
        "pass. Commit it as '^ f'. If an older test asserts the old behaviour, "
        "call `return_to_red`.\n"
        "4. refactor: tidy without adding behaviour; commit each step as '. r'.\n"
        "`advance_tdd_phase` runs every test with coverage and is the only tool "
        "that starts a cycle or changes phase. It needs every production line "
        "changed in the cycle to run in a test, with no comments on those lines. "
        "Call it again after changing the repository outside this server (e.g. "
        "git reset).\n"
        "A refused `write_file` or `edit_file` changes nothing: read the file "
        "before trying again.\n"
        "`run_tests` and `run_coverage` never change the phase. `tdd_status` "
        "shows what is allowed now. Stuck? `rollback_cycle` restarts the cycle "
        "in red. Non-code files and paths matching `TDD_MCP_EXEMPT` skip the "
        "cycle."
    ),
)


def new_service() -> TddService:
    raw = os.environ.get(EXEMPT_ENV_VAR, "")
    return TddService(
        ADAPTERS,
        pending_changes=git_gate.uncommitted_changes,
        history=git_gate,
        exempt=[p.strip() for p in raw.split(",") if p.strip()],
        require_plan=True,
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
    """Show the current TDD phase and what may be written in it.

    Args:
        location: Path to the project root.
    """
    with _refusals_as_tool_errors():
        return service.status(location).render()


PlannedTestSpec = TypedDict(
    "PlannedTestSpec",
    {"name": str, "arrange": str, "act": str, "assert": str},
    total=False,
)


@mcp.tool()
def plan_tests(location: str, tests: list[PlannedTestSpec]) -> str:
    """Plan the task's tests: a TDD session's first step, allowed only in the plan phase.

    List every test the task needs, and no more, smallest behaviour first.
    Order them so each one fails when it is written: a test that would
    already pass is redundant or out of order. Give each a unique name, an
    arrange (the setup), an act (the one call) and an assert (the exact
    expected result). Once every planned test is done you are back in the
    plan phase: plan only what the task still lacks, or stop.

    Args:
        location: Path to the project root.
        tests: The tests in the order to write them.
    """
    with _refusals_as_tool_errors():
        return service.plan_tests(
            location, [planned_test_from(t) for t in tests]
        ).render()


@mcp.tool()
def advance_tdd_phase(location: str, language: LanguageName = "python") -> str:
    """Run every test with coverage and move to the phase the results call for.

    The only tool that starts a cycle or changes phase. Call it first, after
    each refactor, and after any change made outside this server (e.g. a git
    reset). All pass: red, or plan once every planned test is done. Exactly
    one fails: green. Several fail: red, edit the tests until one fails.

    Args:
        location: Path to the project root.
        language: The project's language, which decides how tests are run.
    """
    with _refusals_as_tool_errors():
        return service.advance_tdd_phase(location, language).render()


@mcp.tool()
def return_to_red(location: str) -> str:
    """Go back from green to red to fix tests that no production change can satisfy.

    Use it when older tests still assert the old behaviour, or the new test
    itself is wrong (e.g. a missing import). Uncommitted production changes
    go to git stash.

    Args:
        location: Path to the project root.
    """
    with _refusals_as_tool_errors():
        return service.return_to_red(location).render()


@mcp.tool()
def rollback_cycle(location: str) -> str:
    """Undo the current cycle and restart it in red, when no other tool gets you on.

    Resets to the commit where the cycle started. Dropped commits stay under
    refs/tdd-mcp/, uncommitted work in git stash.

    Args:
        location: Path to the project root.
    """
    with _refusals_as_tool_errors():
        return service.rollback_cycle(location).render()


@mcp.tool()
def run_coverage(location: str, language: LanguageName = "python") -> str:
    """Run every test with coverage and list untested lines. Never changes the phase.

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
    """Run tests without coverage to check progress. Never changes the phase.

    Runs every test by default; narrow it with `path` (a test file or folder)
    and/or `test_name` (pytest -k, vitest -t).

    Args:
        location: Path to the project root.
        path: Test file or folder, relative to `location` (or absolute, inside it).
        test_name: Name, or part of a name, of the test(s) to run.
    """
    with _refusals_as_tool_errors():
        return service.run_tests(location, path, test_name).render()


@mcp.tool()
def write_file(location: str, path: str, content: str) -> str:
    """Create or overwrite a whole file if the phase allows it, then run the tests.

    Tests are writable in red and refactor, production code in green and
    refactor. Overwriting must keep the file's top-level definitions; to
    change part of a file, use edit_file.

    Args:
        location: Path to the project root.
        path: File path, relative to `location` (or absolute, inside it).
        content: The complete new file content.
    """
    with _refusals_as_tool_errors():
        return service.write_file(location, path, content).render()


@mcp.tool()
def edit_file(location: str, path: str, old_string: str, new_string: str) -> str:
    """Replace one exact occurrence of `old_string` if the phase allows it, then run the tests.

    Copy `old_string` from the file as it is now; read the file first if
    unsure.

    Args:
        location: Path to the project root.
        path: File path, relative to `location` (or absolute, inside it).
        old_string: Exact current text; must occur exactly once in the file.
        new_string: Replacement text.
    """
    with _refusals_as_tool_errors():
        return service.edit_file(location, path, old_string, new_string).render()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
