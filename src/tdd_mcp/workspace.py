"""File operations confined to a project root, with snapshots so writes can be undone."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
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


def require_file(target: Path) -> None:
    if not target.is_file():
        raise WorkspaceError(
            f"File {target} does not exist. Create it with write_file instead."
        )


def replace_once(target: Path, old: str, new: str) -> Snapshot:
    require_file(target)
    if not old.strip():
        raise WorkspaceError(
            "old_string is only whitespace, which can't pick out one place. "
            "Include the code line(s) next to the whitespace you want to change."
        )
    if old == new:
        raise WorkspaceError(
            "old_string and new_string are identical, so this edit changes "
            "nothing. To find text, read the file instead."
        )
    content = target.read_bytes().decode("utf-8")
    if "\\n" in old and "\n" not in old and old not in content:
        old, new = old.replace("\\n", "\n"), new.replace("\\n", "\n")
    if "\r\n" in content and "\r\n" not in old:
        old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
    count = content.count(old)
    if count == 0:
        matches = list(re.finditer(_ignoring_trailing_whitespace(old), content))
        if len(matches) == 1:
            start, end = matches[0].span()
            return write_text(target, content[:start] + new + content[end:])
        if new.strip() and new in content:
            raise WorkspaceError(
                "old_string is not in the file, but the file already contains "
                "new_string, so this edit looks already applied. Read the file "
                "before retrying it."
            )
        raise WorkspaceError(
            "Expected exactly one match of old_string, found 0. "
            f"{_closest_text(content, old)}Copy old_string from that text "
            "exactly, or read the file again."
        )
    if count != 1:
        lines = ", ".join(
            str(content.count("\n", 0, match.start()) + 1)
            for match in re.finditer(re.escape(old), content)
        )
        raise WorkspaceError(
            f"Expected exactly one match of old_string, found {count}, on lines "
            f"{lines}. Add surrounding lines from the one you mean until it is "
            "unique."
        )
    return write_text(target, content.replace(old, new))


def _ignoring_trailing_whitespace(old: str) -> str:
    return r"[ \t]*\r?\n".join(
        re.escape(line.rstrip(" \t\r")) for line in old.split("\n")
    )


def _closest_text(content: str, old: str) -> str:
    lines = content.splitlines()
    wanted = old.strip().splitlines()
    first = wanted[0].strip()
    start = max(
        range(len(lines)),
        key=lambda i: SequenceMatcher(None, first, lines[i].strip()).ratio(),
        default=0,
    )
    window = lines[start : start + len(wanted)]
    return (
        f"The closest text in the file, lines {start + 1}-{start + len(window)}:\n"
        + "".join(f"{line}\n" for line in window)
    )


def restore(snapshot: Snapshot) -> None:
    if snapshot.previous is None:
        snapshot.path.unlink(missing_ok=True)
    else:
        snapshot.path.write_bytes(snapshot.previous)


def _snapshot(target: Path) -> Snapshot:
    return Snapshot(target, target.read_bytes() if target.is_file() else None)
