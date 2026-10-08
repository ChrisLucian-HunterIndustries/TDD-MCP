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
        "Enforces the test-driven development cycle when writing code files. "
        "Write every code file through this server's `write_file` or "
        "`edit_file` tools, never with other editing tools. Every reply starts "
        "with 'Phase: <phase>' and says what to do next; follow it. A session "
        "starts in the plan phase, with every code file locked: decide every "
        "test the task needs to be covered completely, and no more, then call "
        "`plan_tests` with each test's name, arrange, act and assert. Each "
        "reply then ends with the plan and the next step for its current test; "
        "do only what that step needs. Each cycle: "
        "(1) call `advance_tdd_phase` — it runs all tests with coverage and is "
        "the only tool that starts a cycle or moves to the next phase; when "
        "all tests pass you are in red, and finishing a cycle checks off the "
        "current planned test. Call it again whenever the repository "
        "changed outside this server (e.g. a git reset) to resync the phase. "
        "(2) Red: write exactly ONE new failing test before any production "
        "code (production code is locked until exactly one test fails, and "
        "adding more than one test keeps you in red). A test that can't be "
        "collected yet, e.g. because it imports code that doesn't exist, "
        "counts as failing. "
        "(3) Green: write production code until the tests pass (tests are "
        "locked meanwhile). If older tests then fail because they assert the "
        "old behaviour, undo your production edits and call `return_to_red` to "
        "update them. (4) Refactor: refactor test or production code — "
        "any edit that breaks the tests or adds a test is automatically "
        "reverted; then call `advance_tdd_phase` to start the next cycle, which "
        "also requires every production line changed this cycle to be covered, "
        "so don't write code for tests that don't exist yet, and refuses while "
        "any line changed this cycle holds a comment (tool directives such as "
        "`# noqa` are fine), so say it with names instead. Call `tdd_status` "
        "any time to see the current phase and what is allowed. `run_coverage` "
        "(a coverage report) and `run_tests` (all tests, a file or folder, or a "
        "single test, without coverage) never change the phase. Non-code files "
        "(docs, config) can be written in any phase and don't run the tests. "
        "Neither do paths matching the server's `TDD_MCP_EXEMPT` patterns. "
        "Coverage includes branches. Commit each step before the next phase's "
        "edits (e.g. '. t' for a new failing test, then '^ f' for the code that "
        "passes it); repeat edits within one phase amend the uncommitted step, "
        "and `advance_tdd_phase` ends it. Stuck with no way to the next phase? "
        "Call `rollback_cycle` to undo the cycle and restart it in red."
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
    """Show the current TDD phase for a project and what may be written in it.

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
    """Plan every test the task needs before writing any code: a TDD session's first step.

    List the tests that cover the task completely, and no more, smallest
    behaviour first. Order them so each one fails when it is written: a test
    that would already pass is redundant or out of order. Give each a unique
    name, its arrange (the setup), its act (the one thing it does) and its
    assert (the exact expected result).
    Allowed only in the plan phase. Each later reply then reminds you of the
    next step for the current test. Once every planned test is done you are
    back in the plan phase: plan only the tests the task still lacks, or stop.

    Args:
        location: Path to the project root.
        tests: The tests in the order to write them, each with a name, arrange, act and assert.
    """
    with _refusals_as_tool_errors():
        return service.plan_tests(
            location, [planned_test_from(t) for t in tests]
        ).render()


@mcp.tool()
def advance_tdd_phase(location: str, language: LanguageName = "python") -> str:
    """Check the whole test suite (with coverage) and move to the next TDD phase.

    The only tool that starts a cycle. Call it first, after each refactor, and
    whenever the repository was changed outside this server (e.g. a git reset):
    the phase is recomputed from the tests. All tests pass: red, write the
    current planned test next, or the plan phase when none is left (call
    plan_tests). Finishing a cycle checks off the current planned test.
    Exactly one test fails: green, make it pass. Several
    fail, or the cycle added several tests: red, edit the tests until exactly
    one new test fails.

    Args:
        location: Path to the project root.
        language: The project's language, which decides how tests are run.
    """
    with _refusals_as_tool_errors():
        return service.advance_tdd_phase(location, language).render()


@mcp.tool()
def return_to_red(location: str) -> str:
    """Go back from green to red to fix tests no production change can satisfy.

    Use it when your production change makes other, older tests fail because
    they still expect the old behaviour, or when the new test itself is wrong
    (e.g. it doesn't import what it uses). Uncommitted production changes are
    set aside in git stash for you. Back in red, fix those tests, keeping your
    new test failing.

    Args:
        location: Path to the project root.
    """
    with _refusals_as_tool_errors():
        return service.return_to_red(location).render()


@mcp.tool()
def rollback_cycle(location: str) -> str:
    """Undo the current cycle when you're stuck, then restart it in red.

    Resets the project to the commit where this cycle started (every test
    passed), dropping the cycle's commits and uncommitted changes. Nothing is
    lost: dropped commits stay under a refs/tdd-mcp/ ref, uncommitted work in
    git stash. Use it when no other tool gets you to the next phase.

    Args:
        location: Path to the project root.
    """
    with _refusals_as_tool_errors():
        return service.rollback_cycle(location).render()


@mcp.tool()
def run_coverage(location: str, language: LanguageName = "python") -> str:
    """Run the full test suite with coverage and show untested lines. Never changes the TDD phase.

    Use it to find untested code. To start a cycle or move to the next phase,
    call `advance_tdd_phase` instead.

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

    Use this to check progress while writing a test or code. Only `advance_tdd_phase`
    and the test runs that `write_file`/`edit_file` trigger advance the cycle, so
    a passing or failing result here unlocks nothing.

    Runs the whole suite by default. Narrow it with `path` (a test file or
    folder) and/or `test_name` (matched against test names: pytest `-k`,
    vitest `-t`) to run all tests in a file or folder, or a single test.
    Requires a cycle started with `advance_tdd_phase`.

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
    next phase, shown on the reply's first line. In red, write one failing
    test before any production code. Overwriting an existing file must
    keep its top-level definitions; use edit_file to change or delete code.

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
