"""Checks that a project's working tree has no uncommitted changes."""

from __future__ import annotations

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
        raise GitError(f"git status failed in {root}: {result.stderr.strip()}")
    return result.stdout.splitlines()
