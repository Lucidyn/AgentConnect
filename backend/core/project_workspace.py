"""Project workspace — bounded filesystem access for coding tasks."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".npm-cache",
}

_PRIORITY_FILES = (
    "README.md",
    "README",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "package.json",
    "Makefile",
    "docker-compose.yml",
)

_FILE_BLOCK_RE = re.compile(
    r"```(?:python|py|txt|json|yaml|yml|toml|md)?(?:\s+([^\n`]+))?\n([\s\S]*?)```",
    re.I,
)
_HEADER_FILE_RE = re.compile(r"^##\s*file:\s*(.+)$", re.I | re.M)


@dataclass
class WorkspaceWriteResult:
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def allowed_workspace_roots() -> list[Path]:
    raw = (settings.workspace_allowed_roots or "").strip()
    if raw:
        roots = []
        for part in raw.split(","):
            part = part.strip()
            if part:
                roots.append(Path(part).expanduser().resolve())
        return roots
    return [_repo_root().resolve(), Path.cwd().resolve()]


def resolve_workspace_path(raw: str, *, create: bool = False) -> Path:
    """Resolve and validate a workspace path against allowed roots."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("工作区路径不能为空")
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()

    if not settings.workspace_enabled:
        raise ValueError("工作区功能未启用（WORKSPACE_ENABLED=false）")

    allowed = allowed_workspace_roots()
    if not any(path == root or root in path.parents for root in allowed):
        allowed_text = ", ".join(str(r) for r in allowed)
        raise ValueError(f"工作区路径不在允许范围内。允许根目录：{allowed_text}")

    if path.exists():
        if not path.is_dir():
            raise ValueError("工作区路径必须是目录")
        return path

    if create and settings.workspace_create_if_missing:
        path.mkdir(parents=True, exist_ok=True)
        logger.info("Created workspace directory: %s", path)
        return path

    raise ValueError(f"工作区目录不存在：{path}")


def _safe_relative(root: Path, rel: str) -> Path:
    rel = rel.strip().lstrip("/").replace("\\", "/")
    if not rel or rel.startswith("..") or "/../" in f"/{rel}/":
        raise ValueError(f"非法相对路径：{rel}")
    target = (root / rel).resolve()
    if root not in target.parents and target != root:
        raise ValueError(f"路径越界：{rel}")
    return target


def read_text_file(root: Path, rel_path: str) -> str:
    target = _safe_relative(root, rel_path)
    if not target.is_file():
        raise FileNotFoundError(rel_path)
    data = target.read_bytes()
    if len(data) > settings.workspace_max_read_bytes:
        raise ValueError(f"文件过大：{rel_path}")
    return data.decode("utf-8", errors="replace")


def write_text_file(root: Path, rel_path: str, content: str) -> None:
    if not settings.workspace_write_enabled:
        raise ValueError("工作区写入未启用（WORKSPACE_WRITE_ENABLED=false）")
    target = _safe_relative(root, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def build_tree_summary(root: Path) -> str:
    """Compact project layout + key file snippets for LLM context."""
    lines: list[str] = [f"工作区：{root}", "", "目录结构："]
    file_paths: list[str] = []

    def walk(current: Path, prefix: str, depth: int) -> None:
        if depth > settings.workspace_max_tree_depth:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return
        count = 0
        for entry in entries:
            if count >= settings.workspace_max_files_in_tree:
                lines.append(f"{prefix}…")
                return
            name = entry.name
            if entry.is_dir():
                if name in _SKIP_DIRS:
                    continue
                lines.append(f"{prefix}{name}/")
                walk(entry, prefix + "  ", depth + 1)
            else:
                rel = entry.relative_to(root).as_posix()
                if len(rel) <= 120:
                    file_paths.append(rel)
                lines.append(f"{prefix}{name}")
            count += 1

    walk(root, "", 0)

    snippets: list[str] = []
    seen: set[str] = set()
    for name in _PRIORITY_FILES:
        candidate = root / name
        if candidate.is_file():
            rel = candidate.relative_to(root).as_posix()
            seen.add(rel)
            snippets.append(_format_snippet(root, rel))
    for rel in file_paths:
        if rel in seen:
            continue
        if rel.endswith((".py", ".toml", ".yaml", ".yml", ".json", ".md")):
            snippets.append(_format_snippet(root, rel))
        if len(snippets) >= settings.workspace_max_snippet_files:
            break

    if snippets:
        lines.extend(["", "关键文件摘要：", *snippets])
    return "\n".join(lines)


def _format_snippet(root: Path, rel: str) -> str:
    try:
        text = read_text_file(root, rel)
    except (OSError, ValueError):
        return f"--- {rel} ---\n(无法读取)"
    limit = min(2000, settings.workspace_max_read_bytes // 4)
    if len(text) > limit:
        text = text[:limit] + "\n…（截断）"
    return f"--- {rel} ---\n{text}"


def parse_file_blocks(content: str) -> list[tuple[str, str]]:
    """Extract (relative_path, code) from LLM output."""
    blocks: list[tuple[str, str]] = []
    for match in _FILE_BLOCK_RE.finditer(content):
        rel = (match.group(1) or "").strip()
        code = (match.group(2) or "").strip()
        if not code:
            continue
        if rel:
            blocks.append((rel, code))
    for match in _HEADER_FILE_RE.finditer(content):
        rel = match.group(1).strip()
        if rel and not any(b[0] == rel for b in blocks):
            start = match.end()
            next_block = _FILE_BLOCK_RE.search(content, start)
            if next_block and next_block.group(1):
                continue
            if next_block:
                blocks.append((rel, next_block.group(2).strip()))
    return blocks


def apply_file_blocks(root: Path, content: str) -> WorkspaceWriteResult:
    result = WorkspaceWriteResult()
    blocks = parse_file_blocks(content)
    if not blocks:
        return result
    for rel, code in blocks:
        try:
            write_text_file(root, rel, code.rstrip() + "\n")
            result.written.append(rel)
        except (ValueError, OSError) as exc:
            logger.warning("Skip write %s: %s", rel, exc)
            result.skipped.append(f"{rel}: {exc}")
    return result


def workspace_from_context(ctx: dict) -> Path | None:
    raw = (ctx or {}).get("workspace_path") or ""
    if not raw:
        return None
    try:
        return resolve_workspace_path(raw, create=False)
    except ValueError as exc:
        logger.warning("Invalid workspace in context: %s", exc)
        return None
