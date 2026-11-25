from app.graph.call_graph import CallGraph


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
                "file": sym.file_path,
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