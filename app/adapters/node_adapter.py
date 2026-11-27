"""Node.js / Nest / Express 预览索引（装饰器路由，无完整 CALLS）。"""

from __future__ import annotations

import re
from pathlib import Path

from app.adapters.protocol import IREndpoint, IRSymbol, RepoGraphIR

_NEST_DECORATOR = re.compile(
    r"@(?:Get|Post|Put|Patch|Delete|Head|Options)\s*\(\s*['\"`]([^'\"`]*)['\"`]",
    re.IGNORECASE,
)
_EXPRESS_ROUTE = re.compile(
    r"(?:router|app)\.(get|post|put|patch|delete)\s*\(\s*['\"`]([^'\"`]+)['\"`]",
    re.IGNORECASE,
)
_SKIP = frozenset({".git", "node_modules", "dist", "build", "coverage"})


def index_nodejs_preview(
    *,
    repo_id: str,
    repo_full_name: str,
    repo_dir: Path,
    scan_root: str,
) -> RepoGraphIR:
    root = (repo_dir / scan_root.strip().lstrip("/")).resolve()
    symbols: list[IRSymbol] = []
    endpoints: list[IREndpoint] = []
    if not root.is_dir():
        return RepoGraphIR(
            repo_id=repo_id,
            repo_full_name=repo_full_name,
            language="nodejs",
            meta={"preview": True, "error": "scan_root_missing"},
        )

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(p in SKIP for p in path.parts):
            continue
        if path.suffix.lower() not in (".ts", ".js", ".mjs", ".cjs"):
            continue
        rel = path.relative_to(repo_dir.resolve()).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            m = _NEST_DECORATOR.search(line)
            if m:
                method_m = re.search(r"@(\w+)\s*\(", line, re.I)
                method = (method_m.group(1) if method_m else "Get").upper()
                if method == "OPTIONS":
                    method = "OPTIONS"
                route = m.group(1) or "/"
                qual = f"{rel}:L{i}"
                uid = f"{repo_id}:{rel}:{qual}"
                symbols.append(
                    IRSymbol(
                        uid=uid,
                        qualname=qual,
                        file_path=rel,
                        kind="endpoint",
                        start_line=i,
                        end_line=i,
                        is_endpoint=True,
                        http_method=method,
                        route_path=route or "/",
                    )
                )
                endpoints.append(
                    IREndpoint(
                        method=method,
                        path=route or "/",
                        symbol_uid=uid,
                        file_path=rel,
                        qualname=qual,
                    )
                )
            em = _EXPRESS_ROUTE.search(line)
            if em:
                method = em.group(1).upper()
                route = em.group(2)
                qual = f"{rel}:L{i}"
                uid = f"{repo_id}:{rel}:{qual}"
                symbols.append(
                    IRSymbol(
                        uid=uid,
                        qualname=qual,
                        file_path=rel,
                        kind="endpoint",
                        start_line=i,
                        end_line=i,
                        is_endpoint=True,
                        http_method=method,
                        route_path=route,
                    )
                )
                endpoints.append(
                    IREndpoint(
                        method=method,
                        path=route,
                        symbol_uid=uid,
                        file_path=rel,
                        qualname=qual,
                    )
                )

    return RepoGraphIR(
        repo_id=repo_id,
        repo_full_name=repo_full_name,
        language="nodejs",
        symbols=symbols,
        call_edges=[],
        endpoints=endpoints,
        meta={
            "preview": True,
            "symbol_count": len(symbols),
            "api_count": len(endpoints),
            "call_graph": "pending",
        },
    )