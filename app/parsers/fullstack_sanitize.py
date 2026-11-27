"""全栈影响面输出：委托 fullstack_normalize，并兼容既有 API 字段。"""

from __future__ import annotations

from pathlib import Path

from app.parsers.fullstack_normalize import clean_repo_rel_path, normalize_fullstack_impact


def _split_dir(full: str) -> tuple[str, str]:
    p = Path(full)
    return (full.rsplit("/", 1)[0] if "/" in full else "", p.name)


def _raw_components_from_payload(payload: dict) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for key in ("affected_routes", "affected_pages"):
        for item in payload.get(key) or []:
            if not isinstance(item, dict):
                continue
            comp = item.get("component_file") or item.get("file") or ""
            route = item.get("route_path") or item.get("route") or "—"
            if comp in seen:
                continue
            seen.add(comp)
            rows.append({"route": route, "component": comp, "file": comp})
    return rows


def _raw_api_calls_from_payload(payload: dict) -> list[dict]:
    out: list[dict] = []
    for c in payload.get("frontend_api_calls") or []:
        if not isinstance(c, dict):
            continue
        out.append(
            {
                "file": c.get("file"),
                "method": c.get("backend_method") or c.get("method"),
                "endpoint": c.get("backend_path") or c.get("path") or c.get("api"),
                "line": c.get("line"),
            }
        )
    return out


def tree_sitter_scan_shape(impact: dict) -> dict:
    """将 vue_ts_index 追溯结果整理为 normalize 期望的 components / api_calls 形态。"""
    components: list[dict] = []
    seen: set[str] = set()
    for item in (impact.get("affected_routes") or []) + (impact.get("affected_pages") or []):
        if not isinstance(item, dict):
            continue
        comp = item.get("component_file") or item.get("file") or ""
        if not comp or comp in seen:
            continue
        seen.add(comp)
        components.append(
            {
                "route": item.get("route_path") or item.get("route") or "—",
                "component": comp,
            }
        )
    api_calls: list[dict] = []
    for c in impact.get("frontend_api_calls") or []:
        if not isinstance(c, dict):
            continue
        api_calls.append(
            {
                "file": c.get("file"),
                "method": c.get("backend_method") or c.get("method"),
                "endpoint": c.get("backend_path") or c.get("path"),
                "line": c.get("line"),
            }
        )
    return {**impact, "components": components, "api_calls": api_calls}


def sanitize_fullstack_payload(
    tree_sitter_output: dict,
    *,
    repo_root: str | None = None,
    worktree_dir: str | Path | None = None,
) -> dict:
    """
    业务层全栈清洗入口。

    示例（分析沙箱 worktree）::

        result = sanitize_fullstack_payload(
            tree_sitter_output,
            worktree_dir=worktree_dir,  # .../data/worktrees/<uuid>/<repo_name>
        )

    或直接调用 normalize_fullstack_impact(..., repo_root=worktree_dir)。
    """
    root = worktree_dir if worktree_dir is not None else repo_root
    if root is not None:
        root = str(Path(root).resolve())

    raw_components = tree_sitter_output.get("components")
    if raw_components is None:
        raw_components = _raw_components_from_payload(tree_sitter_output)

    raw_api_calls = tree_sitter_output.get("api_calls")
    if raw_api_calls is None:
        raw_api_calls = _raw_api_calls_from_payload(tree_sitter_output)

    norm = normalize_fullstack_impact(
        raw_components=raw_components,
        raw_api_calls=raw_api_calls,
        repo_root=root,
    )

    affected_pages: list[dict] = []
    for c in norm["components"]:
        dir_part, name = _split_dir(c["file"])
        affected_pages.append(
            {
                "route_path": c["route"],
                "route_name": name,
                "component_file": c["file"],
                "component_name": c["name"],
                "component_dir": dir_part,
                "router_file": "SPA / React" if c["route"] == "—" else None,
            }
        )

    aggregated_legacy: list[dict] = []
    matched_flat: list[dict] = []
    for row in norm["matched_api_calls"]:
        dir_part, _ = _split_dir(row["file"])
        aggregated_legacy.append(
            {
                "file": row["file"],
                "file_name": row["file_name"],
                "file_dir": dir_part,
                "lines": row["lines"],
                "backend_paths": [row["endpoint"]],
                "backend_methods": [row["method"]],
            }
        )
        for ln in row["lines"]:
            matched_flat.append(
                {
                    "file": row["file"],
                    "line": ln,
                    "method": row["method"],
                    "backend_method": row["method"],
                    "backend_path": row["endpoint"],
                    "path": row["endpoint"],
                }
            )

    out = dict(tree_sitter_output)
    out.update(norm)
    out["affected_routes"] = affected_pages
    out["affected_pages"] = affected_pages
    out["frontend_api_calls"] = matched_flat
    out["frontend_api_calls_aggregated"] = aggregated_legacy
    out["unresolved_dynamic_calls"] = [
        {"file": u["file"], "line": ln}
        for u in norm["unresolved_calls"]
        for ln in u.get("lines") or []
    ]
    return out