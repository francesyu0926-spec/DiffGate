"""全栈影响面：路径清洗、降噪与按文件/接口聚合。"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

# 匹配 worktrees/<uuid>/ 或 data/worktrees/<uuid>/<repo_name>/ 前缀
_WORKTREE_PREFIX_RE = re.compile(
    r"^(?:.*?[/\\])?worktrees[/\\][0-9a-fA-F-]{8,36}[/\\](?:[^/\\]+[/\\])?"
)


def clean_repo_rel_path(raw_path: str, repo_root: str | None = None) -> str:
    """
    将 worktree 物理路径清洗为干净的仓库内相对路径。

    示例:
      'data/worktrees/0aaf8810-.../francesyu0926-spec_QuantLens/frontend/src/App.tsx'
      -> 'frontend/src/App.tsx'
    """
    if not raw_path:
        return ""

    if repo_root:
        try:
            rel = Path(raw_path).resolve().relative_to(Path(repo_root).resolve())
            return rel.as_posix()
        except ValueError:
            pass

    normalized = raw_path.replace("\\", "/").lstrip("./")
    cleaned = _WORKTREE_PREFIX_RE.sub("", normalized)

    # 已以仓库一级目录开头则不再截取，避免 frontend/src/... 被误裁成 src/...
    _TOP_LEVEL_PREFIXES = ("frontend/", "backend/", "web/", "packages/")
    if any(cleaned.startswith(p) for p in _TOP_LEVEL_PREFIXES):
        return cleaned

    for anchor in ("frontend/", "backend/", "web/", "src/", "app/", "packages/"):
        idx = cleaned.find(anchor)
        if idx > 0:
            cleaned = cleaned[idx:]
            break

    return cleaned


def normalize_fullstack_impact(
    raw_components: list[dict[str, Any]],
    raw_api_calls: list[dict[str, Any]],
    repo_root: str | None = None,
) -> dict[str, Any]:
    """对 tree-sitter 扫描结果做路径清洗、过滤 '-' 占位、按 (method, endpoint, file) 聚合行号。"""
    seen_components: set[tuple[str, str]] = set()
    cleaned_components: list[dict[str, Any]] = []

    for item in raw_components:
        raw_file = item.get("component") or item.get("file") or ""
        clean_file = clean_repo_rel_path(str(raw_file), repo_root)
        route = (item.get("route") or item.get("route_path") or "").strip() or "—"

        dedup_key = (route, clean_file)
        if not clean_file or dedup_key in seen_components:
            continue
        seen_components.add(dedup_key)

        cleaned_components.append(
            {
                "route": route,
                "file": clean_file,
                "name": Path(clean_file).name,
            }
        )

    matched_groups: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    unresolved_groups: dict[str, set[int]] = defaultdict(set)

    for call in raw_api_calls:
        raw_file = call.get("file") or ""
        clean_file = clean_repo_rel_path(str(raw_file), repo_root)
        if not clean_file:
            continue

        method = (call.get("method") or call.get("backend") or call.get("backend_method") or "-").strip().upper()
        endpoint = (
            call.get("endpoint")
            or call.get("api")
            or call.get("backend_path")
            or call.get("path")
            or "-"
        )
        endpoint = str(endpoint).split("?")[0].strip() or "-"
        line = call.get("line")

        if method in ("", "-") or endpoint in ("", "-"):
            if isinstance(line, int):
                unresolved_groups[clean_file].add(line)
            continue

        key = (method, endpoint, clean_file)
        if isinstance(line, int):
            matched_groups[key].add(line)
        else:
            matched_groups.setdefault(key, set())

    aggregated_calls: list[dict[str, Any]] = []
    for (method, endpoint, clean_file), lines_set in sorted(matched_groups.items()):
        sorted_lines = sorted(lines_set)
        aggregated_calls.append(
            {
                "method": method,
                "endpoint": endpoint,
                "file": clean_file,
                "file_name": Path(clean_file).name,
                "lines": sorted_lines,
                "lines_display": ", ".join(f"L{ln}" for ln in sorted_lines),
                "first_line": sorted_lines[0] if sorted_lines else 1,
            }
        )

    unresolved_calls = [
        {
            "file": f,
            "lines": sorted(lns),
            "lines_display": ", ".join(f"L{ln}" for ln in sorted(lns)),
        }
        for f, lns in sorted(unresolved_groups.items())
    ]

    return {
        "components": cleaned_components,
        "matched_api_calls": aggregated_calls,
        "unresolved_calls": unresolved_calls,
        "unresolved_count": len(unresolved_calls),
    }