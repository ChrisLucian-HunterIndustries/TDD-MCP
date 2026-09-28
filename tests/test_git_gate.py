import subprocess
from pathlib import Path

import pytest

from tdd_mcp.git_gate import GitError, uncommitted_changes


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    return tmp_path


def test_clean_tree_has_no_changes(repo: Path):
    assert uncommitted_changes(repo) == []


def test_lists_unstaged_modifications(repo: Path):
    (repo / "a.txt").write_text("b")
    assert uncommitted_changes(repo) == [" M a.txt"]


def test_lists_staged_modifications(repo: Path):
    (repo / "a.txt").write_text("b")
    _git(repo, "add", "a.txt")
    assert uncommitted_changes(repo) == ["M  a.txt"]


def test_lists_each_untracked_file(repo: Path):
    (repo / "src").mkdir()
    (repo / "src" / "new.py").write_text("")
    assert uncommitted_changes(repo) == ["?? src/new.py"]


def test_ignores_gitignored_files(repo: Path):
    (repo / "ignored.txt").write_text("")
    assert uncommitted_changes(repo) == []


def test_only_considers_changes_under_the_given_directory(repo: Path):
    (repo / "pkg").mkdir()
    (repo / "a.txt").write_text("changed outside pkg")
    assert uncommitted_changes(repo / "pkg") == []


def test_outside_a_repository_is_an_error(tmp_path: Path):
    with pytest.raises(GitError, match="not a git repository"):
        uncommitted_changes(tmp_path)
