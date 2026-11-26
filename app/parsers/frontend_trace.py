"""Vue/TS 全栈追溯入口。"""

from __future__ import annotations

from pathlib import Path

from app.parsers.fullstack_sanitize import sanitize_fullstack_payload, tree_sitter_scan_shape
from app.parsers.vue_ts_index import (
    FrontendIndex,
    merge_frontend_impact,
    scan_frontend_repo,
    trace_frontend_for_backend_apis,
    trace_frontend_impact,
)

SUPPORTED = [".vue", ".ts", ".tsx", ".js", ".jsx"]


def build_fullstack_impact(
    worktree_dir: Path,
    changed_files: set[str],
    *,
    scan_roots: tuple[str, ...] = ("web", "frontend", "."),
    backend_apis: list[dict] | None = None,
) -> dict:
    """
    在分析沙箱（主克隆或 git worktree）内扫描前端并做路径清洗。

    ``worktree_dir`` 即 ``normalize_fullstack_impact(..., repo_root=...)`` 所用根目录。
    """
    worktree_dir = worktree_dir.resolve()
    index = scan_frontend_repo(worktree_dir, scan_roots=scan_roots)
    diff_impact = trace_frontend_impact(index, changed_files, worktree_dir)
    backend_impact = trace_frontend_for_backend_apis(index, backend_apis or [], worktree_dir)
    impact = merge_frontend_impact(diff_impact, backend_impact)
    tree_sitter_output = tree_sitter_scan_shape(
        {
            "engine": "tree-sitter",
            "supported": SUPPORTED,
            "index_stats": {
                "component_files": len(index.components),
                "routes": len(index.routes),
                "api_calls": len(index.api_calls),
            },
            **impact,
        }
    )
    return sanitize_fullstack_payload(tree_sitter_output, worktree_dir=worktree_dir)


__all__ = [
    "FrontendIndex",
    "build_fullstack_impact",
    "scan_frontend_repo",
    "trace_frontend_impact",
]