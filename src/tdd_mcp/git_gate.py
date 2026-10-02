"""Checks that a project's working tree has no uncommitted changes."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class GitError(ValueError):
    """Raised when git can't report the working tree's status."""


def uncommitted_changes(root: Path) -> list[str]:
    """`git status --porcelain` lines for staged, unstaged, and untracked changes under `root`."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", "."],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise GitError(
            f"git status failed in {root}: {result.stderr.strip()}. The project "
            "must be a git repository: ask the user to run git init and commit, "
            "then retry."
        )
    return result.stdout.splitlines()


def head_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def is_ancestor(root: Path, commit: str) -> bool:
    """Whether `commit` is HEAD or one of its ancestors (false once a reset rewinds past it)."""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        check=False,
        cwd=root,
        capture_output=True,
    )
    return result.returncode == 0


def rollback(root: Path, commit: str) -> str:
    """Reset to `commit`; returns the ref that keeps the commits dropped from HEAD."""
    head = head_commit(root)
    backup = f"refs/tdd-mcp/rollback-{head[:12]}"
    for args in (["update-ref", backup, head], ["reset", "--hard", commit]):
        subprocess.run(["git", *args], check=True, cwd=root, capture_output=True)
    return backup


_HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")


def changed_lines(root: Path, base: str) -> dict[str, frozenset[int]]:
    """Lines added or modified under `root` since commit `base`, by root-relative path."""
    diff = subprocess.run(
        ["git", "diff", "-U0", "--relative", "--no-color", base, "--", "."],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    changed: dict[str, set[int]] = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[len("+++ b/") :] if line.startswith("+++ b/") else None
        elif path and (hunk := _HUNK.match(line)):
            start, count = int(hunk[1]), int(hunk[2] or 1)
            changed.setdefault(path, set()).update(range(start, start + count))
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "."],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    for path in untracked.splitlines():
        line_count = len((root / path).read_bytes().splitlines())
        changed[path] = set(range(1, line_count + 1))
    return {path: frozenset(lines) for path, lines in changed.items() if lines}
