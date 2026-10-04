"""File operations confined to a project root, with snapshots so writes can be undone."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(ValueError):
    """Raised when a file operation is invalid or unsafe."""


@dataclass(frozen=True)
class Snapshot:
    path: Path
    previous: bytes | None


def resolve_inside(root: Path, path: str) -> Path:
    """Resolve `path` (relative to `root`, or absolute), refusing anything outside `root`."""
    resolved_root = root.resolve()
    target = (resolved_root / path).resolve()
    if not target.is_relative_to(resolved_root):
        raise WorkspaceError(
            f"Path {path!r} is outside the project root {resolved_root}. "
            "Pass a path inside it, relative to location."
        )
    return target


def write_text(target: Path, content: str) -> Snapshot:
    if target.is_dir():
        raise WorkspaceError(f"{target} is a directory. Pass a file path instead.")
    snapshot = _snapshot(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8"))
    return snapshot


def replace_once(target: Path, old: str, new: str) -> Snapshot:
    if not target.is_file():
        raise WorkspaceError(
            f"File {target} does not exist. Create it with write_file instead."
        )
    content = target.read_bytes().decode("utf-8")
    if "\r\n" in content and "\r\n" not in old:
        old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
    count = content.count(old)
    if count == 0:
        matches = list(re.finditer(_ignoring_trailing_whitespace(old), content))
        if len(matches) == 1:
            start, end = matches[0].span()
            return write_text(target, content[:start] + new + content[end:])
    if count != 1:
        raise WorkspaceError(
            f"Expected exactly one match of old_string, found {count}. Read the "
            "file, copy old_string exactly, and add surrounding lines until it "
            "is unique."
        )
    return write_text(target, content.replace(old, new))


def _ignoring_trailing_whitespace(old: str) -> str:
    return r"[ \t]*\r?\n".join(
        re.escape(line.rstrip(" \t\r")) for line in old.split("\n")
    )


def restore(snapshot: Snapshot) -> None:
    if snapshot.previous is None:
        snapshot.path.unlink(missing_ok=True)
    else:
        snapshot.path.write_bytes(snapshot.previous)


def _snapshot(target: Path) -> Snapshot:
    return Snapshot(target, target.read_bytes() if target.is_file() else None)
