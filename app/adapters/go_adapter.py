"""Go 静态索引（符号、Gin/Echo/http 路由、调用边 → RepoGraphIR）。"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from app.adapters.protocol import IRCallEdge, IREndpoint, IRSymbol, RepoGraphIR
from app.config import get_settings

_SKIP_DIRS = frozenset({".git", "vendor", "node_modules", "dist", "bin"})

_PACKAGE = re.compile(r"^\s*package\s+(\w+)")
_FUNC = re.compile(r"^func\s+(?:\(\s*\w+\s+\*?(\w+)\s*\)\s+)?(\w+)\s*\(")
_GIN_ROUTE = re.compile(
    r"\b(\w+)\.(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s*\(\s*\"([^\"]*)\"",
    re.I,
)
_GIN_GROUP = re.compile(r"(\w+)\s*:=\s*\w+\.Group\s*\(\s*\"([^\"]*)\"\s*\)")
_ECHO_ROUTE = re.compile(
    r"\b(\w+)\.(Get|Post|Put|Patch|Delete)\s*\(\s*\"([^\"]*)\"",
)
_HTTP_HANDLE = re.compile(r"http\.HandleFunc\s*\(\s*\"([^\"]+)\"")
_MUX_HANDLE = re.compile(r"mux\.Handle(?:Func)?\s*\(\s*\"([^\"]+)\"")
_CALL = re.compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w+)\s*\(")
_GRPC_CALL = re.compile(r"\b(\w+)Client\)\.(\w+)\s*\(")


def _go_uid(repo_id: str, file_path: str, qualname: str) -> str:
    return f"{repo_id}:{file_path}:{qualname}"


def _join_route(prefix: str, sub: str) -> str:
    p = (prefix or "").strip()
    s = (sub or "").strip()
    if not p:
        return "/" + s.lstrip("/") if s else "/"
    if not p.startswith("/"):
        p = "/" + p
    if not s:
        return p
    if not s.startswith("/"):
        s = "/" + s
    return (p.rstrip("/") + s).replace("//", "/")


def _should_skip_go(rel: str) -> bool:
    name = rel.replace("\\", "/")
    base = name.rsplit("/", 1)[-1]
    if base.endswith("_test.go"):
        return True
    if base.endswith(".pb.go"):
        return True
    if "/vendor/" in f"/{name}/":
        return True
    return False


def _scan_go_files(root: Path, repo_dir: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if not root.is_dir():
        return rows
    for path in root.rglob("*.go"):
        if any(p in _SKIP_DIRS for p in path.parts):
            continue
        rel = path.relative_to(repo_dir.resolve()).as_posix()
        if _should_skip_go(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rows.append((rel, text))
    return rows


def _index_from_source(
    *,
    repo_id: str,
    repo_full_name: str,
    repo_dir: Path,
    scan_root: str,
) -> RepoGraphIR:
    root = (repo_dir / (scan_root or ".").strip().lstrip("/")).resolve()
    symbols: list[IRSymbol] = []
    endpoints: list[IREndpoint] = []
    edges: list[IRCallEdge] = []
    group_prefix: dict[str, str] = {}

    for rel, text in _scan_go_files(root, repo_dir):
        pkg = ""
        current_func = ""
        current_receiver = ""
        lines = text.splitlines()

        for i, line in enumerate(lines, start=1):
            pm = _PACKAGE.match(line)
            if pm:
                pkg = pm.group(1)

            gm = _GIN_GROUP.search(line)
            if gm:
                group_prefix[gm.group(1)] = gm.group(2)

            fm = _FUNC.match(line)
            if fm:
                current_receiver = fm.group(1) or ""
                current_func = fm.group(2) or ""
                if current_func in ("if", "for", "switch"):
                    continue
                if current_receiver:
                    qual = f"{pkg}.(*{current_receiver}).{current_func}"
                else:
                    qual = f"{pkg}.{current_func}" if pkg else current_func
                uid = _go_uid(repo_id, rel, qual)
                symbols.append(
                    IRSymbol(
                        uid=uid,
                        qualname=qual,
                        file_path=rel,
                        kind="method" if current_receiver else "function",
                        start_line=i,
                        end_line=min(i + 60, len(lines)),
                    )
                )

            for vm, method, route in _GIN_ROUTE.findall(line):
                http_method = method.upper()
                prefix = group_prefix.get(vm, "")
                full = _join_route(prefix, route)
                qual = f"{pkg}.{current_func or f'route:L{i}'}"
                if current_receiver:
                    qual = f"{pkg}.(*{current_receiver}).{current_func or f'route:L{i}'}"
                uid = _go_uid(repo_id, rel, f"{qual}#route")
                endpoints.append(
                    IREndpoint(method=http_method, path=full, symbol_uid=uid, file_path=rel, qualname=qual)
                )
                symbols.append(
                    IRSymbol(
                        uid=uid,
                        qualname=qual,
                        file_path=rel,
                        kind="endpoint",
                        start_line=i,
                        end_line=i,
                        is_endpoint=True,
                        http_method=http_method,
                        route_path=full,
                    )
                )

            for vm, method, route in _ECHO_ROUTE.findall(line):
                http_method = method.upper()
                full = _join_route(group_prefix.get(vm, ""), route)
                qual = f"{pkg}.route:L{i}"
                uid = _go_uid(repo_id, rel, qual)
                endpoints.append(
                    IREndpoint(method=http_method, path=full, symbol_uid=uid, file_path=rel, qualname=qual)
                )

            hm = _HTTP_HANDLE.search(line) or _MUX_HANDLE.search(line)
            if hm:
                full = hm.group(1)
                qual = f"{pkg}.http:L{i}"
                uid = _go_uid(repo_id, rel, qual)
                endpoints.append(
                    IREndpoint(method="GET", path=full, symbol_uid=uid, file_path=rel, qualname=qual)
                )

            if current_func:
                caller = f"{pkg}.(*{current_receiver}).{current_func}" if current_receiver else f"{pkg}.{current_func}"
                for owner, meth in _CALL.findall(line):
                    if owner == pkg:
                        continue
                    edges.append(IRCallEdge(caller_qualname=caller, callee_qualname=f"{owner}.{meth}"))
                for client, meth in _GRPC_CALL.findall(line):
                    edges.append(
                        IRCallEdge(caller_qualname=caller, callee_qualname=f"grpc:{client}.{meth}")
                    )

    return RepoGraphIR(
        repo_id=repo_id,
        repo_full_name=repo_full_name,
        language="go",
        symbols=symbols,
        call_edges=edges,
        endpoints=endpoints,
        meta={
            "symbol_count": len(symbols),
            "edge_count": len(edges),
            "api_count": len(endpoints),
            "index_mode": "regex_go",
        },
    )


def _index_from_cli(repo_dir: Path, scan_root: str) -> dict | None:
    cli = (get_settings().go_analyzer_bin or "").strip()
    if not cli or not Path(cli).is_file():
        return None
    try:
        proc = subprocess.run(
            [cli, "--repo", str(repo_dir), "--scan-root", scan_root or "."],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


def index_go(
    *,
    repo_id: str,
    repo_full_name: str,
    repo_dir: Path,
    scan_root: str,
) -> RepoGraphIR:
    payload = _index_from_cli(repo_dir, scan_root)
    if isinstance(payload, dict) and payload.get("symbols"):
        symbols = [IRSymbol(**s) for s in payload.get("symbols", [])]
        endpoints = [IREndpoint(**e) for e in payload.get("endpoints", [])]
        edges = [IRCallEdge(**e) for e in payload.get("call_edges", [])]
        return RepoGraphIR(
            repo_id=repo_id,
            repo_full_name=repo_full_name,
            language="go",
            symbols=symbols,
            call_edges=edges,
            endpoints=endpoints,
            meta={**(payload.get("meta") or {}), "index_mode": "diffgate-go-ast"},
        )
    return _index_from_source(
        repo_id=repo_id,
        repo_full_name=repo_full_name,
        repo_dir=repo_dir,
        scan_root=scan_root or ".",
    )