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
        raise GitError(f"git status failed in {root}: {result.stderr.strip()}")
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
    return {path: frozenset(lines) for path, lines in changed.items() if lines}
