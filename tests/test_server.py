import asyncio
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from tdd_mcp import server
from tdd_mcp.server import edit_file, mcp, run_coverage, tdd_status, write_file


@pytest.fixture(autouse=True)
def fresh_service(monkeypatch):
    monkeypatch.setattr(server, "service", server.new_service())


def test_python_red_green_refactor_cycle(tmp_path: Path):
    location = str(tmp_path)
    (tmp_path / "calc.py").write_text("")

    assert tdd_status(location).startswith("Phase: coverage_required")
    assert run_coverage(location).startswith("Phase: red")

    with pytest.raises(ToolError, match="not allowed in the red phase"):
        write_file(location, "calc.py", "def add(a, b):\n    return a + b\n")

    red = write_file(
        location,
        "test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    assert red.startswith("Phase: green")

    green = write_file(location, "calc.py", "def add(a, b):\n    return a - b\n")
    assert green.startswith("Phase: green")

    fixed = edit_file(location, "calc.py", "a - b", "a + b")
    assert fixed.startswith("Phase: refactor")

    reverted = edit_file(location, "calc.py", "a + b", "a * b")
    assert "reverted" in reverted
    assert "a + b" in (tmp_path / "calc.py").read_text()

    assert run_coverage(location).startswith("Phase: red")


def test_refusal_reasons_reach_the_client(tmp_path: Path):
    arguments = {"location": str(tmp_path), "path": "a.py", "content": ""}
    with pytest.raises(ToolError, match="No TDD cycle started"):
        asyncio.run(mcp.call_tool("write_file", arguments))


def test_main_runs_the_server(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp, "run", lambda: calls.append("run"))
    server.main()
    assert calls == ["run"]


def test_server_instructions_explain_the_cycle():
    assert mcp.instructions is not None
    for word in ("run_coverage", "write_file", "edit_file", "fail", "refactor"):
        assert word in mcp.instructions
