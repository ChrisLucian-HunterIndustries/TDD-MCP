"""File operations confined to a project root, with snapshots so writes can be undone."""

from __future__ import annotations

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
            f"Path {path!r} is outside the project root {resolved_root}"
        )
    return target


def write_text(target: Path, content: str) -> Snapshot:
    snapshot = _snapshot(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8"))
    return snapshot


def replace_once(target: Path, old: str, new: str) -> Snapshot:
    if not target.is_file():
        raise WorkspaceError(f"File {target} does not exist")
    content = target.read_bytes().decode("utf-8")
    count = content.count(old)
    if count != 1:
        raise WorkspaceError(f"Expected exactly one match of old_string, found {count}")
    return write_text(target, content.replace(old, new))


def restore(snapshot: Snapshot) -> None:
    if snapshot.previous is None:
        snapshot.path.unlink(missing_ok=True)
    else:
        snapshot.path.write_bytes(snapshot.previous)


def _snapshot(target: Path) -> Snapshot:
    return Snapshot(target, target.read_bytes() if target.is_file() else None)
