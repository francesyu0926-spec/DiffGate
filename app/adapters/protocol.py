"""统一中间 JSON：供 Neo4j 图谱与质量门禁消费。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class IRSymbol:
    uid: str
    qualname: str
    file_path: str
    kind: str
    start_line: int
    end_line: int
    is_endpoint: bool = False
    http_method: str | None = None
    route_path: str | None = None


@dataclass
class IRCallEdge:
    caller_qualname: str
    callee_qualname: str


@dataclass
class IREndpoint:
    method: str
    path: str
    symbol_uid: str
    file_path: str
    qualname: str


@dataclass
class RepoGraphIR:
    repo_id: str
    repo_full_name: str
    language: str
    symbols: list[IRSymbol] = field(default_factory=list)
    call_edges: list[IRCallEdge] = field(default_factory=list)
    endpoints: list[IREndpoint] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_python_index(
        *,
        repo_id: str,
        repo_full_name: str,
        symbols,
        graph,
        uid_fn,
    ) -> "RepoGraphIR":
        ir_symbols: list[IRSymbol] = []
        endpoints: list[IREndpoint] = []
        for sym in symbols:
            uid = uid_fn(repo_id, sym.file_path, sym.qualified_name)
            is_ep = bool(sym.is_api_handler)
            ir_symbols.append(
                IRSymbol(
                    uid=uid,
                    qualname=sym.qualified_name,
                    file_path=sym.file_path,
                    kind=sym.kind,
                    start_line=sym.start_line,
                    end_line=sym.end_line,
                    is_endpoint=is_ep,
                    http_method=sym.http_method,
                    route_path=sym.route_path,
                )
            )
            if is_ep and sym.route_path:
                endpoints.append(
                    IREndpoint(
                        method=(sym.http_method or "GET").upper(),
                        path=sym.route_path,
                        symbol_uid=uid,
                        file_path=sym.file_path,
                        qualname=sym.qualified_name,
                    )
                )
        edges = [
            IRCallEdge(caller_qualname=caller, callee_qualname=callee)
            for caller, callees in graph.forward.items()
            for callee in callees
        ]
        return RepoGraphIR(
            repo_id=repo_id,
            repo_full_name=repo_full_name,
            language="python",
            symbols=ir_symbols,
            call_edges=edges,
            endpoints=endpoints,
            meta={"symbol_count": len(ir_symbols), "edge_count": len(edges), "api_count": len(endpoints)},
        )