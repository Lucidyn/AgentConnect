"""Tests for project workspace path resolution and file apply."""

import pytest

from backend.core.project_workspace import (
    apply_file_blocks,
    build_tree_summary,
    check_workspace_path,
    get_or_build_tree_summary,
    parse_file_blocks,
    resolve_workspace_path,
    write_text_file,
)


@pytest.fixture
def workspace_root(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.config.settings.workspace_allowed_roots", str(tmp_path))
    return tmp_path


def test_resolve_rejects_path_outside_roots(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr("backend.config.settings.workspace_allowed_roots", str(allowed))
    with pytest.raises(ValueError, match="不在允许范围"):
        resolve_workspace_path(str(outside))


def test_resolve_creates_missing_dir_when_enabled(workspace_root):
    target = workspace_root / "new_project"
    resolved = resolve_workspace_path(str(target), create=True)
    assert resolved == target.resolve()
    assert target.is_dir()


def test_check_workspace_path_allows_future_create(workspace_root):
    target = workspace_root / "future"
    result = check_workspace_path(str(target))
    assert result.valid is True
    assert result.will_create is True


def test_parse_file_blocks_with_path_in_fence():
    content = "```python src/app.py\nprint('hi')\n```"
    blocks = parse_file_blocks(content)
    assert blocks == [("src/app.py", "print('hi')")]


def test_apply_file_blocks_writes_files(workspace_root):
    content = "```python pkg/main.py\nx = 1\n```"
    result = apply_file_blocks(workspace_root, content)
    assert result.written == ["pkg/main.py"]
    assert (workspace_root / "pkg" / "main.py").read_text(encoding="utf-8") == "x = 1\n"


def test_build_tree_summary_includes_readme(workspace_root):
    (workspace_root / "README.md").write_text("# Demo", encoding="utf-8")
    summary = build_tree_summary(workspace_root)
    assert "README.md" in summary
    assert "# Demo" in summary


def test_write_rejects_traversal(workspace_root):
    with pytest.raises(ValueError, match="非法相对路径"):
        write_text_file(workspace_root, "../escape.py", "bad")


def test_write_rejects_env_file(workspace_root):
    with pytest.raises(ValueError, match="敏感文件"):
        write_text_file(workspace_root, ".env", "SECRET=1")


def test_write_rejects_disallowed_extension(workspace_root):
    with pytest.raises(ValueError, match="不允许的文件类型"):
        write_text_file(workspace_root, "bin/evil.exe", "data")


def test_get_or_build_tree_summary_uses_cache(workspace_root):
    (workspace_root / "README.md").write_text("# cached", encoding="utf-8")
    tree = build_tree_summary(workspace_root)
    cached = get_or_build_tree_summary(
        workspace_root,
        cached=tree,
        cached_path=str(workspace_root.resolve()),
    )
    assert cached == tree
    assert "# cached" in cached
