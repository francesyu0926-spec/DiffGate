from __future__ import annotations

from pathlib import Path

from app.graph.call_graph import CallGraph
from app.parsers.vue_ts_index import _normalize_http_path
from app.parsers.fullstack_normalize import clean_repo_rel_path


def sanitize_graph_paths(graph: dict) -> dict:
    """将图中 node.file 洗为仓库相对路径（修复历史 worktree 脏数据）。"""
    nodes: list[dict] = []
    for n in graph.get("nodes") or []:
        row = dict(n)
        if row.get("file"):
            row["file"] = clean_repo_rel_path(str(row["file"]))
        nodes.append(row)
    return {**graph, "nodes": nodes}


def strip_frontend_layer(graph: dict) -> dict:
    """移除全栈图层，便于用最新 fullstack 结果重绘前端节点。"""
    nodes = list(graph.get("nodes") or [])
    fe_ids = {str(n["id"]) for n in nodes if n.get("type") == "frontend"}
    nodes = [n for n in nodes if n.get("type") != "frontend"]
    edges = [
        e
        for e in (graph.get("edges") or [])
        if str(e.get("source")) not in fe_ids
        and str(e.get("target")) not in fe_ids
        and e.get("kind") != "http_client"
    ]
    out = {**graph, "nodes": nodes, "edges": edges}
    out.pop("has_frontend_layer", None)
    return out


def build_g6_payload(graph: CallGraph, changed: list[str]) -> dict:
    """Build AntV G6 nodes/edges for impact subgraph (changed → upstream → APIs)."""
    changed_set = set(changed)
    seeds = graph._expand_seeds(changed_set)
    upstream = graph.resolve_callers(seeds)

    nodes: list[dict] = []
    for name in sorted(upstream):
        sym = graph.symbols.get(name)
        if not sym:
            continue
        short = name.split(".")[-1]
        if sym.is_api_handler:
            node_type = "api"
        elif name in changed_set:
            node_type = "changed"
        else:
            node_type = "symbol"
        nodes.append(
            {
                "id": name,
                "label": short,
                "type": node_type,
                "file": clean_repo_rel_path(str(sym.file_path)),
                "line": sym.start_line,
                "end_line": sym.end_line,
                "method": (sym.http_method or "").upper() if sym.http_method else None,
                "route": sym.route_path,
            }
        )

    node_ids = {n["id"] for n in nodes}

    def resolve_targets(callee: str) -> list[str]:
        hits = [n for n in node_ids if n == callee or n.endswith(f".{callee}")]
        if hits:
            return hits
        if "." in callee:
            cls, _, method = callee.rpartition(".")
            cls_tail = cls.split(".")[-1]
            hits = [
                n
                for n in node_ids
                if n.split(".")[-1] == method
                and (n.endswith(f".{cls}.{method}") or cls_tail in n.split("."))
            ]
            if hits:
                return hits
        return [n for n in node_ids if n.split(".")[-1] == callee]

    edges: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()
    for caller in node_ids:
        for callee in graph.forward.get(caller, ()):
            for target in resolve_targets(callee):
                key = (caller, target)
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                edges.append({"source": caller, "target": target})

    return {"nodes": nodes, "edges": edges}


def augment_graph_with_frontend(
    graph: dict,
    fullstack: dict | None,
    backend_apis: list[dict],
) -> dict:
    """在拓扑中追加前端消费方节点，并连到对应 API。"""
    if not fullstack:
        return sanitize_graph_paths(graph)
    graph = sanitize_graph_paths(strip_frontend_layer(graph))
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    api_by_path: dict[str, str] = {}
    for n in nodes:
        if n.get("type") != "api":
            continue
        route = n.get("route") or ""
        if route:
            api_by_path[_normalize_http_path(str(route))] = str(n["id"])
    for api in backend_apis or []:
        p = _normalize_http_path(str(api.get("path") or ""))
        if p and p not in api_by_path:
            hid = str(api.get("handler") or api.get("path") or "")
            if hid:
                api_by_path[p] = hid

    seen_nodes: set[str] = {str(n["id"]) for n in nodes}
    seen_edges: set[tuple[str, str]] = {
        (str(e.get("source")), str(e.get("target"))) for e in edges
    }
    for row in fullstack.get("frontend_api_calls") or []:
        file_path = clean_repo_rel_path(str(row.get("file") or ""))
        if not file_path:
            continue
        fid = f"frontend:{file_path}:{row.get('line', 0)}"
        if fid not in seen_nodes:
            seen_nodes.add(fid)
            stem = Path(file_path).name
            nodes.append(
                {
                    "id": fid,
                    "label": stem,
                    "type": "frontend",
                    "file": file_path,
                    "line": int(row.get("line") or 1),
                    "end_line": int(row.get("line") or 1),
                    "method": row.get("method"),
                    "route": row.get("backend_path") or row.get("path"),
                }
            )
        target_path = _normalize_http_path(str(row.get("backend_path") or row.get("path") or ""))
        api_id = api_by_path.get(target_path)
        if not api_id:
            continue
        key = (fid, api_id)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append({"source": fid, "target": api_id, "kind": "http_client"})

    return {**graph, "nodes": nodes, "edges": edges, "has_frontend_layer": True}