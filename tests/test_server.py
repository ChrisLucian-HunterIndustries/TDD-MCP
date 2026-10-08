import asyncio
import subprocess
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from tdd_mcp import server
from tdd_mcp.server import advance_tdd_phase, edit_file, mcp, tdd_status, write_file


@pytest.fixture(autouse=True)
def fresh_service(monkeypatch):
    service = server.new_service()
    service.require_plan = False
    monkeypatch.setattr(server, "service", service)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit_all(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "step")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "calc.py").write_text("")
    _commit_all(tmp_path)
    return tmp_path


def test_python_red_green_refactor_cycle(repo: Path):
    location = str(repo)

    assert tdd_status(location).startswith("Phase: coverage_required")
    assert advance_tdd_phase(location).startswith("Phase: red")

    with pytest.raises(ToolError, match="not allowed in the red phase"):
        write_file(location, "calc.py", "def add(a, b):\n    return a + b\n")

    red = write_file(
        location,
        "test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    assert red.startswith("Phase: green")

    with pytest.raises(ToolError, match=r"Uncommitted changes .*\?\? test_calc\.py"):
        write_file(location, "calc.py", "def add(a, b):\n    return a + b\n")
    _commit_all(repo)

    green = write_file(location, "calc.py", "def add(a, b):\n    return a - b\n")
    assert green.startswith("Phase: green")
    _commit_all(repo)

    fixed = edit_file(location, "calc.py", "a - b", "a + b")
    assert fixed.startswith("Phase: refactor")
    _commit_all(repo)

    reverted = edit_file(location, "calc.py", "a + b", "a * b")
    assert "reverted" in reverted
    assert "a + b" in (repo / "calc.py").read_text()

    assert advance_tdd_phase(location).startswith("Phase: red")


def test_advance_tdd_phase_starts_the_cycle(repo: Path):
    assert server.advance_tdd_phase(str(repo)).startswith("Phase: red")


def test_the_server_makes_planning_the_tests_its_first_step():
    assert server.new_service().require_plan


def test_plan_tests_tool_takes_each_tests_arrange_act_and_assert(repo: Path):
    location = str(repo)
    server.service.require_plan = True
    assert advance_tdd_phase(location).startswith("Phase: plan")

    planned = server.plan_tests(
        location,
        [{"name": "adds", "arrange": "calc", "act": "add 1 and 2", "assert": "3"}],
    )

    assert planned.startswith("Phase: red")
    assert "Arrange: calc. Act: add 1 and 2. Assert: 3." in planned


def test_plan_tests_tool_accepts_a_misspelt_key(repo: Path):
    location = str(repo)
    server.service.require_plan = True
    advance_tdd_phase(location)

    planned = server.plan_tests(
        location,
        [{"name": "adds", "arrang": "calc", "act": "add 1 and 2", "assert": "3"}],
    )

    assert planned.startswith("Phase: red")
    assert "Arrange: calc." in planned


def test_plan_tests_says_every_test_must_fail_when_written():
    description = " ".join(server.plan_tests.__doc__.split())
    assert (
        "Order them so each one fails when it is written: a test that would "
        "already pass is redundant or out of order."
    ) in description


def test_return_to_red_tool_reopens_tests_from_green(repo: Path):
    location = str(repo)
    advance_tdd_phase(location)
    write_file(
        location,
        "test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    _commit_all(repo)

    assert server.return_to_red(location).startswith("Phase: red")


def test_rollback_cycle_tool_undoes_the_cycles_commits(repo: Path):
    location = str(repo)
    advance_tdd_phase(location)
    write_file(
        location,
        "test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    _commit_all(repo)
    write_file(location, "calc.py", "def add(a, b):\n    return a + b\n")
    _commit_all(repo)

    report = server.rollback_cycle(location)

    assert report.startswith("Phase: red")
    assert not (repo / "test_calc.py").exists()
    assert (repo / "calc.py").read_text() == ""


def test_run_coverage_tool_reports_without_starting_the_cycle(repo: Path):
    report = server.run_coverage(str(repo))

    assert report.startswith("Phase: coverage_required")
    assert "Coverage run passed (phase unchanged)." in report
    assert tdd_status(str(repo)).startswith("Phase: coverage_required")


def test_edits_outside_a_git_repository_are_refused(tmp_path: Path):
    advance_tdd_phase(str(tmp_path))
    with pytest.raises(ToolError, match="not a git repository"):
        write_file(str(tmp_path), "notes.md", "x")


def test_untested_production_code_blocks_the_next_cycle(repo: Path):
    location = str(repo)
    advance_tdd_phase(location)
    write_file(
        location,
        "test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    _commit_all(repo)
    write_file(
        location,
        "calc.py",
        "def add(a, b):\n    return a + b\n\n\ndef unused():\n    return 0\n",
    )
    _commit_all(repo)

    blocked = advance_tdd_phase(location)

    assert blocked.startswith("Phase: refactor")
    assert "calc.py: 6." in blocked

    edit_file(location, "calc.py", "\n\n\ndef unused():\n    return 0\n", "\n")
    _commit_all(repo)
    assert advance_tdd_phase(location).startswith("Phase: red")


def test_comments_added_this_cycle_block_the_next_cycle(repo: Path):
    location = str(repo)
    advance_tdd_phase(location)
    write_file(
        location,
        "test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    _commit_all(repo)
    write_file(location, "calc.py", "def add(a, b):\n    # sum\n    return a + b\n")
    _commit_all(repo)

    blocked = advance_tdd_phase(location)

    assert blocked.startswith("Phase: refactor")
    assert "hold comments: calc.py: 2." in blocked


def test_refusal_reasons_reach_the_client(tmp_path: Path):
    arguments = {"location": str(tmp_path), "path": "a.py", "content": ""}
    with pytest.raises(ToolError, match="No TDD cycle started"):
        asyncio.run(mcp.call_tool("write_file", arguments))


def test_run_tests_tool_runs_a_selection_without_changing_phase(tmp_path: Path):
    location = str(tmp_path)
    (tmp_path / "test_calc.py").write_text(
        "def test_add():\n    pass\n\n\ndef test_sub():\n    assert False\n\n\n"
        "def test_mul():\n    assert False\n"
    )
    phase_line = advance_tdd_phase(location).splitlines()[0]

    result = asyncio.run(
        mcp.call_tool(
            "run_tests",
            {"location": location, "path": "test_calc.py", "test_name": "test_add"},
        )
    )

    text = result.content[0].text
    assert text.startswith(f"{phase_line}\n")
    assert "Tests passed (not a coverage run; phase unchanged)." in text
    assert "1 passed, 2 deselected" in text


def test_main_runs_the_server(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp, "run", lambda: calls.append("run"))
    server.main()
    assert calls == ["run"]


@pytest.mark.parametrize(
    ("value", "patterns"),
    [
        (None, ()),
        ("", ()),
        ("scripts/*", ("scripts/*",)),
        (" scripts/* , *.pyi ,", ("scripts/*", "*.pyi")),
    ],
)
def test_exempt_patterns_come_from_environment(monkeypatch, value, patterns):
    if value is None:
        monkeypatch.delenv("TDD_MCP_EXEMPT", raising=False)
    else:
        monkeypatch.setenv("TDD_MCP_EXEMPT", value)
    assert server.new_service().exempt == patterns


def test_server_instructions_explain_the_cycle():
    assert mcp.instructions is not None
    for word in (
        "plan_tests",
        "arrange",
        "run_coverage",
        "run_tests",
        "write_file",
        "edit_file",
        "fail",
        "refactor",
    ):
        assert word in mcp.instructions
