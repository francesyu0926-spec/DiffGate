"""仓库类型 → 语言适配器路由。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.adapters.protocol import RepoGraphIR

_REPO_TYPES: list[dict[str, Any]] = [
    {
        "id": "backend_python",
        "label": "后端 (Python)",
        "language": "python",
        "index_supported": True,
        "coverage_hint": "coverage.py / CI 探针",
    },
    {
        "id": "frontend",
        "label": "前端 (TS/JS)",
        "language": "frontend",
        "index_supported": True,
        "coverage_hint": "前端契约扫描（非行覆盖率）",
    },
    {
        "id": "backend_node",
        "label": "后端 (Node.js/TS)",
        "language": "nodejs",
        "index_supported": True,
        "preview_only": True,
        "coverage_hint": "c8 / nyc (规划)",
    },
    {
        "id": "backend_go",
        "label": "后端 (Go)",
        "language": "go",
        "index_supported": False,
        "coming_soon": True,
        "coverage_hint": "go test -coverprofile (规划)",
    },
    {
        "id": "backend_java",
        "label": "后端 (Java)",
        "language": "java",
        "index_supported": False,
        "coming_soon": True,
        "coverage_hint": "JaCoCo Agent (规划)",
    },
]

_ALIASES = {
    "backend": "backend_python",
    "python": "backend_python",
    "backend_py": "backend_python",
}


def normalize_repo_type(repo_type: str | None) -> str:
    raw = (repo_type or "backend_python").strip().lower()
    return _ALIASES.get(raw, raw)


def list_repo_type_options() -> list[dict[str, Any]]:
    return [dict(x) for x in _REPO_TYPES]


def repo_type_index_supported(repo_type: str | None) -> bool:
    key = normalize_repo_type(repo_type)
    row = next((r for r in _REPO_TYPES if r["id"] == key), None)
    return bool(row and row.get("index_supported"))


def index_repository_graph(
    *,
    repo_type: str,
    repo_id: str,
    repo_full_name: str,
    repo_dir: Path,
    scan_root: str,
) -> RepoGraphIR | None:
    """按仓库类型产出统一中间协议（已实现语言）。"""
    key = normalize_repo_type(repo_type)
    if key == "backend_python":
        from app.adapters.python_adapter import index_python
        return index_python(
            repo_id=repo_id,
            repo_full_name=repo_full_name,
            repo_dir=repo_dir,
            scan_root=scan_root,
        )
    if key == "frontend":
        return None
    if key == "backend_node":
        from app.adapters.node_adapter import index_nodejs_preview

        return index_nodejs_preview(
            repo_id=repo_id,
            repo_full_name=repo_full_name,
            repo_dir=repo_dir,
            scan_root=scan_root,
        )
    return None


def cache_ir(repo_id: str, ir: RepoGraphIR) -> None:
    from app.graph import local_cache

    local_cache.write_json(f"ir/{repo_id}.json", ir.to_dict())