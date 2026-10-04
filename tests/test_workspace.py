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


def test_write_text_refuses_to_overwrite_a_directory(tmp_path: Path):
    with pytest.raises(WorkspaceError, match="is a directory"):
        write_text(tmp_path, "x = 1\n")


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


def test_replace_once_matches_lf_text_in_crlf_file(tmp_path: Path):
    target = tmp_path / "a.py"
    target.write_bytes(b"a = 1\r\nb = 2\r\n")
    replace_once(target, "a = 1\nb = 2\n", "a = 1\nb = 3\n")
    assert target.read_bytes() == b"a = 1\r\nb = 3\r\n"


def test_replace_once_tolerates_trailing_whitespace_differences(tmp_path: Path):
    """Gemma4 couldn't see trailing spaces or space-only blank lines to copy them."""
    target = tmp_path / "a.py"
    target.write_text("a = 1  \n    \nb = 2\n")
    replace_once(target, "a = 1\n        \nb = 2", "a = 1\nb = 3")
    assert target.read_text() == "a = 1\nb = 3\n"


def test_replace_once_says_when_the_edit_looks_already_applied(tmp_path: Path):
    """Gemma4 retried an edit it had already made and committed, three times."""
    target = tmp_path / "a.py"
    target.write_text("a = 2\n")
    with pytest.raises(WorkspaceError, match="already contains new_string"):
        replace_once(target, "a = 1", "a = 2")


def test_replace_once_shows_the_closest_text_when_nothing_matches(tmp_path: Path):
    """A model that copied old_string wrong needs the real text, not "copy exactly"."""
    target = tmp_path / "a.py"
    target.write_text("def f():\n    return 1\n\ndef g():\n    return 2\n")
    with pytest.raises(WorkspaceError) as refusal:
        replace_once(target, "def g():\n    return 3", "def g():\n    return 4")
    assert "lines 4-5:\ndef g():\n    return 2\n" in str(refusal.value)


def test_replace_once_names_the_lines_of_ambiguous_matches(tmp_path: Path):
    """Gemma4 sent "break" (3 matches) without knowing which lines to widen around."""
    target = tmp_path / "a.py"
    target.write_text("break\nx = 1\n    break\n")
    with pytest.raises(WorkspaceError, match="found 2, on lines 1, 3"):
        replace_once(target, "break", "")


def test_replace_once_refuses_a_whitespace_only_old_string(tmp_path: Path):
    """Gemma4 sent bare indentation as old_string, which matched 90 times."""
    target = tmp_path / "a.py"
    target.write_text("if x:\n    y = 1\n")
    with pytest.raises(WorkspaceError, match="only whitespace"):
        replace_once(target, "    ", "")


def test_replace_once_refuses_an_edit_that_changes_nothing(tmp_path: Path):
    """Gemma4's no-op edits passed the tests and looked like progress."""
    target = tmp_path / "a.py"
    target.write_text("x = 1\n")
    with pytest.raises(WorkspaceError, match="identical"):
        replace_once(target, "x = 1", "x = 1")


def test_replace_once_reads_escaped_line_breaks_as_line_breaks(tmp_path: Path):
    """Gemma4 sent backslash-n characters instead of line breaks in old_string."""
    target = tmp_path / "a.py"
    target.write_text("a = 1\nb = 2\n")
    replace_once(target, "a = 1\\nb = 2", "a = 1\\nb = 3")
    assert target.read_text() == "a = 1\nb = 3\n"


def test_write_preserves_line_endings_verbatim(tmp_path: Path):
    target = tmp_path / "a.py"
    write_text(target, "a\r\nb\n")
    assert target.read_bytes() == b"a\r\nb\n"
