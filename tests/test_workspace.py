from pathlib import Path

import pytest

from tdd_mcp.workspace import (
    WorkspaceError,
    replace_once,
    resolve_inside,
    restore,
    write_text,
)


def test_resolves_relative_path_inside_root(tmp_path: Path):
    assert resolve_inside(tmp_path, "src/a.py") == tmp_path.resolve() / "src" / "a.py"


def test_resolves_absolute_path_inside_root(tmp_path: Path):
    target = tmp_path / "a.py"
    assert resolve_inside(tmp_path, str(target)) == target.resolve()


@pytest.mark.parametrize("path", ["../escape.py", "src/../../escape.py"])
def test_rejects_relative_path_escaping_root(tmp_path: Path, path: str):
    with pytest.raises(WorkspaceError, match="outside"):
        resolve_inside(tmp_path / "root", path)


def test_rejects_absolute_path_outside_root(tmp_path: Path):
    (tmp_path / "root").mkdir()
    with pytest.raises(WorkspaceError, match="outside"):
        resolve_inside(tmp_path / "root", str(tmp_path / "other.py"))


def test_rejects_symlink_escaping_root(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted")
    with pytest.raises(WorkspaceError, match="outside"):
        resolve_inside(root, "link/escape.py")


def test_write_text_creates_parent_directories(tmp_path: Path):
    target = tmp_path / "pkg" / "a.py"
    write_text(target, "x = 1\n")
    assert target.read_text() == "x = 1\n"


def test_restore_after_write_to_new_file_deletes_it(tmp_path: Path):
    target = tmp_path / "a.py"
    snapshot = write_text(target, "x = 1\n")
    restore(snapshot)
    assert not target.exists()


def test_restore_after_write_to_existing_file_restores_content(tmp_path: Path):
    target = tmp_path / "a.py"
    target.write_text("old\n")
    snapshot = write_text(target, "new\n")
    restore(snapshot)
    assert target.read_text() == "old\n"


def test_replace_once_replaces_unique_occurrence(tmp_path: Path):
    target = tmp_path / "a.py"
    target.write_text("a = 1\nb = 2\n")
    snapshot = replace_once(target, "b = 2", "b = 3")
    assert target.read_text() == "a = 1\nb = 3\n"
    restore(snapshot)
    assert target.read_text() == "a = 1\nb = 2\n"


def test_replace_once_requires_existing_file(tmp_path: Path):
    with pytest.raises(WorkspaceError, match="does not exist"):
        replace_once(tmp_path / "missing.py", "a", "b")


@pytest.mark.parametrize(("content", "count"), [("x\n", 0), ("a\na\n", 2)])
def test_replace_once_requires_exactly_one_match(
    tmp_path: Path, content: str, count: int
):
    target = tmp_path / "a.py"
    target.write_text(content)
    with pytest.raises(WorkspaceError, match=f"found {count}"):
        replace_once(target, "a", "b")
    assert target.read_text() == content


def test_write_preserves_line_endings_verbatim(tmp_path: Path):
    target = tmp_path / "a.py"
    write_text(target, "a\r\nb\n")
    assert target.read_bytes() == b"a\r\nb\n"
