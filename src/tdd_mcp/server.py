"""MCP server that enforces the red/green/refactor test-driven development cycle."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from tdd_mcp.languages import ADAPTERS, LanguageName
from tdd_mcp.service import TddService

mcp = MCPServer(
    "test-driven-development",
    instructions=(
        "Enforces the test-driven development cycle when writing code files. "
        "Write every code file through this server's `write_file` or "
        "`edit_file` tools, never with other editing tools. Each cycle: "
        "(1) call `run_coverage` — all tests must pass, and the coverage "
        "report shows what is untested; (2) write a new or changed test that "
        "makes the suite fail (production code is locked until it does); "
        "(3) write production code until the tests pass (tests are locked "
        "meanwhile); (4) refactor test or production code — any edit that "
        "breaks the tests is automatically reverted; then call "
        "`run_coverage` to start the next cycle. Call `tdd_status` any time "
        "to see the current phase and what is allowed. Non-code files (docs, "
        "config) can be written in any phase and don't run the tests."
    ),
)


def new_service() -> TddService:
    return TddService(ADAPTERS)


service = new_service()


@mcp.tool()
def tdd_status(location: str) -> str:
    """Show the current TDD phase for a project and what may be written in it.

    Args:
        location: Path to the project root.
    """
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
    return service.run_coverage(location, language).render()


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
    return service.edit_file(location, path, old_string, new_string).render()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
