import subprocess
from pathlib import Path

import pytest

from tdd_mcp.git_gate import (
    GitError,
    changed_lines,
    head_commit,
    is_ancestor,
    uncommitted_changes,
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


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


def test_head_commit_is_the_checked_out_commit(repo: Path):
    assert head_commit(repo) == _git(repo, "rev-parse", "HEAD").strip()


def test_is_ancestor_of_later_commits_but_not_after_a_reset_rewinds_past_it(
    repo: Path,
):
    base = head_commit(repo)
    (repo / "a.txt").write_text("b")
    _git(repo, "commit", "-am", "later")
    later = head_commit(repo)
    assert is_ancestor(repo, base)

    _git(repo, "reset", "--hard", base)
    assert not is_ancestor(repo, later)


def test_changed_lines_lists_added_and_modified_lines_since_a_commit(repo: Path):
    (repo / "a.txt").write_text("one\ntwo\nthree\n")
    _git(repo, "commit", "-am", "base")
    base = head_commit(repo)
    (repo / "a.txt").write_text("one\nTWO\nthree\nfour\n")
    _git(repo, "commit", "-am", "change")

    assert changed_lines(repo, base) == {"a.txt": frozenset({2, 4})}


def test_changed_lines_counts_every_line_of_untracked_files(repo: Path):
    (repo / "src").mkdir()
    (repo / "src" / "new.py").write_text("x = 1\ny = 2\n")
    assert changed_lines(repo, head_commit(repo)) == {"src/new.py": frozenset({1, 2})}


def test_rollback_resets_to_a_commit_and_keeps_the_dropped_commits_under_a_ref(
    repo: Path,
):
    from tdd_mcp import git_gate

    base = head_commit(repo)
    (repo / "a.txt").write_text("b")
    _git(repo, "commit", "-am", "dropped")
    dropped = head_commit(repo)

    backup = git_gate.rollback(repo, base)

    assert head_commit(repo) == base
    assert (repo / "a.txt").read_text() == "a"
    assert _git(repo, "rev-parse", backup).strip() == dropped


def test_rollback_stashes_uncommitted_and_untracked_work(repo: Path):
    from tdd_mcp import git_gate

    (repo / "a.txt").write_text("b")
    (repo / "new.py").write_text("x = 1\n")

    git_gate.rollback(repo, head_commit(repo))

    assert uncommitted_changes(repo) == []
    _git(repo, "stash", "pop")
    assert (repo / "a.txt").read_text() == "b"
    assert (repo / "new.py").read_text() == "x = 1\n"


def test_set_aside_stashes_only_the_given_paths_including_new_files(repo: Path):
    from tdd_mcp import git_gate

    (repo / "a.txt").write_text("b")
    (repo / "new.py").write_text("x = 1\n")
    (repo / "keep.txt").write_text("kept")

    git_gate.set_aside(repo, ["a.txt", "new.py"])

    assert uncommitted_changes(repo) == ["?? keep.txt"]
    _git(repo, "stash", "pop")
    assert (repo / "a.txt").read_text() == "b"
    assert (repo / "new.py").read_text() == "x = 1\n"


def test_rollback_refuses_to_drop_changes_outside_the_project(repo: Path):
    from tdd_mcp import git_gate

    (repo / "pkg").mkdir()
    base = head_commit(repo)
    (repo / "a.txt").write_text("outside pkg")
    _git(repo, "commit", "-am", "outside")
    head = head_commit(repo)

    with pytest.raises(GitError, match="outside"):
        git_gate.rollback(repo / "pkg", base)
    assert head_commit(repo) == head
