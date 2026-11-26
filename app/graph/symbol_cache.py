"""仓库符号表本地缓存，支撑增量 AST 索引。"""

from __future__ import annotations

from app.config import get_settings
from app.graph import local_cache
from app.parsers.python_ast import SymbolDef


def _safe_key(repo_key: str) -> str:
    return repo_key.replace("/", "_")


def _serialize(symbols: list[SymbolDef]) -> dict:
    return {
        "symbols": [
            {
                "qualified_name": s.qualified_name,
                "file_path": s.file_path,
                "kind": s.kind,
                "start_line": s.start_line,
                "end_line": s.end_line,
                "calls": list(s.calls),
                "decorators": list(s.decorators),
                "is_api_handler": s.is_api_handler,
                "http_method": s.http_method,
                "route_path": s.route_path,
            }
            for s in symbols
        ]
    }


def _deserialize(payload: dict) -> list[SymbolDef]:
    out: list[SymbolDef] = []
    for row in payload.get("symbols") or []:
        if not isinstance(row, dict):
            continue
        out.append(
            SymbolDef(
                qualified_name=str(row["qualified_name"]),
                file_path=str(row["file_path"]),
                kind=str(row.get("kind") or "function"),
                start_line=int(row.get("start_line") or 1),
                end_line=int(row.get("end_line") or 1),
                calls=list(row.get("calls") or []),
                decorators=list(row.get("decorators") or []),
                is_api_handler=bool(row.get("is_api_handler")),
                http_method=row.get("http_method"),
                route_path=row.get("route_path"),
            )
        )
    return out


def load_symbols(repo_key: str) -> list[SymbolDef] | None:
    if get_settings().use_redis:
        return None
    data = local_cache.read_json(f"cg/{_safe_key(repo_key)}/symbols.json")
    if not data:
        return None
    return _deserialize(data)


def save_symbols(repo_key: str, symbols: list[SymbolDef]) -> None:
    if get_settings().use_redis:
        return
    local_cache.write_json(f"cg/{_safe_key(repo_key)}/symbols.json", _serialize(symbols))