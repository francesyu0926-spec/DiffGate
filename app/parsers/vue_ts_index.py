"""Vue / TypeScript 全栈影响索引：组件 → 路由 → 前端 API 调用。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from app.parsers.treesitter_lang import parser_for_path

VUE_SCRIPT_RE = re.compile(
    r"<script(?:\s+[^>]*)?>(.*?)</script>",
    re.DOTALL | re.IGNORECASE,
)
IMPORT_FROM_RE = re.compile(
    r"""import\s+(?:[\w*{}\s,]+)\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
IMPORT_SIDE_RE = re.compile(r"""import\s+['"]([^'"]+)['"]""", re.MULTILINE)
ROUTE_PATH_RE = re.compile(r"""path\s*:\s*['"]([^'"]+)['"]""")
ROUTE_NAME_RE = re.compile(r"""name\s*:\s*['"]([^'"]+)['"]""")
COMPONENT_REF_RE = re.compile(
    r"""component\s*:\s*(?:\(\)\s*=>\s*import\s*\(\s*['"]([^'"]+)['"]\s*\)|['"]([^'"]+)['"])"""
)
API_CALL_FALLBACK_RE = re.compile(
    r"""
    (?:axios|apiClient|http)\.(get|post|put|patch|delete)\s*\(\s*['"`]([^'"`]+)['"`]
    |fetch\s*\(\s*['"`]([^'"`]+)['"`]
    |fetch\s*\(\s*`([^`]+)`
    |\$fetch\s*\(\s*['"`]([^'"`]+)['"`]
    """,
    re.IGNORECASE | re.VERBOSE,
)
SKIP_DIR = frozenset({".git", "node_modules", "dist", "build", ".nuxt", "coverage", "__pycache__"})


@dataclass
class FrontendApiCall:
    method: str
    path: str
    file_path: str
    line: int


@dataclass
class RouteEntry:
    path: str
    route_name: str | None
    component_import: str | None
    file_path: str
    line: int


@dataclass
class ComponentUnit:
    file_path: str
    imports: list[str] = field(default_factory=list)
    api_calls: list[FrontendApiCall] = field(default_factory=list)


@dataclass
class FrontendIndex:
    components: list[ComponentUnit]
    routes: list[RouteEntry]
    api_calls: list[FrontendApiCall]

    def to_dict(self) -> dict:
        return {
            "components": [
                {
                    "file": c.file_path,
                    "imports": c.imports,
                    "api_calls": [
                        {"method": a.method, "path": a.path, "file": a.file_path, "line": a.line}
                        for a in c.api_calls
                    ],
                }
                for c in self.components
            ],
            "routes": [
                {
                    "path": r.path,
                    "name": r.route_name,
                    "component_import": r.component_import,
                    "file": r.file_path,
                    "line": r.line,
                }
                for r in self.routes
            ],
            "api_calls": [
                {"method": a.method, "path": a.path, "file": a.file_path, "line": a.line}
                for a in self.api_calls
            ],
        }


def _norm_rel(repo_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def extract_vue_scripts(source: str) -> str:
    blocks = VUE_SCRIPT_RE.findall(source)
  # omit duplicated template
    return "\n\n".join(block.strip() for block in blocks if block.strip())


def _walk_calls_ts(source: bytes, parser, file_path: str) -> list[FrontendApiCall]:
    if not parser:
        return []
    tree = parser.parse(source)
    calls: list[FrontendApiCall] = []

    stack = [tree.root_node]
    http_methods = {"get", "post", "put", "patch", "delete", "head", "options"}

    while stack:
        node = stack.pop()
        stack.extend(reversed(node.children))

        if node.type != "call_expression":
            continue
        fn = node.child_by_field_name("function")
        if fn is None:
            continue
        text = source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
        method = "GET"
        path: str | None = None

        if fn.type == "member_expression":
            prop = fn.child_by_field_name("property")
            obj = fn.child_by_field_name("object")
            if prop and prop.text:
                m = prop.text.decode("utf-8").lower()
                if m in http_methods:
                    method = m.upper()
                    if obj and obj.text:
                        root = obj.text.decode("utf-8").lower()
                        if root in ("axios", "http", "apiclient", "client", "api"):
                            args = node.child_by_field_name("arguments")
                            if args and args.child_count > 0:
                                first = args.children[0]
                                if first.type == "string" and first.text:
                                    path = first.text.decode("utf-8").strip("\"'`")
        elif fn.type == "identifier" and fn.text:
            name = fn.text.decode("utf-8")
            if name in ("fetch", "$fetch"):
                method = "GET"
                args = node.child_by_field_name("arguments")
                if args and args.child_count > 0:
                    first = args.children[0]
                    if first.type == "string" and first.text:
                        path = first.text.decode("utf-8").strip("\"'`")

        if not path:
            m = API_CALL_FALLBACK_RE.search(text)
            if m:
                method = (m.group(1) or "GET").upper()
                path = m.group(2) or m.group(3) or m.group(4)
        if path:
            line = node.start_point[0] + 1
            calls.append(FrontendApiCall(method=method, path=path, file_path=file_path, line=line))
    return calls


def _imports_from_source(text: str) -> list[str]:
    out: list[str] = []
    for pat in (IMPORT_FROM_RE, IMPORT_SIDE_RE):
        out.extend(m.group(1) for m in pat.finditer(text))
    return out


def _routes_from_text(text: str, file_path: str) -> list[RouteEntry]:
    routes: list[RouteEntry] = []
    if "createRouter" not in text and "routes" not in text:
        return routes
    lines = text.splitlines()
    block = text
    for m in ROUTE_PATH_RE.finditer(block):
        path = m.group(1)
        start = m.start()
        line_no = block[:start].count("\n") + 1
        window = block[max(0, start - 120) : start + 400]
        name_m = ROUTE_NAME_RE.search(window)
        comp_m = COMPONENT_REF_RE.search(window)
        comp = None
        if comp_m:
            comp = comp_m.group(1) or comp_m.group(2)
        routes.append(
            RouteEntry(
                path=path,
                route_name=name_m.group(1) if name_m else None,
                component_import=comp,
                file_path=file_path,
                line=line_no,
            )
        )
    return routes


def _resolve_import_to_file(repo_root: Path, from_file: str, spec: str) -> str | None:
    if spec.startswith("."):
        base = (repo_root / Path(from_file).parent / spec).resolve()
        for cand in (base, base.with_suffix(".ts"), base.with_suffix(".vue"), base / "index.ts"):
            if cand.is_file():
                try:
                    return cand.relative_to(repo_root.resolve()).as_posix()
                except ValueError:
                    return None
    return None


def scan_frontend_repo(repo_root: Path, scan_roots: Iterable[str] = ("web", "frontend", ".")) -> FrontendIndex:
    repo_root = repo_root.resolve()
    components: list[ComponentUnit] = []
    routes: list[RouteEntry] = []
    all_calls: list[FrontendApiCall] = []

    roots: list[Path] = []
    for sr in scan_roots:
        p = (repo_root / sr.strip().lstrip("/")).resolve()
        if p.is_dir() and str(p).startswith(str(repo_root)):
            roots.append(p)
    if not roots:
        roots = [repo_root]

    seen_files: set[str] = set()
    for base in roots:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR for part in path.parts):
                continue
            rel = _norm_rel(repo_root, path)
            if rel in seen_files:
                continue
            low = rel.lower()
            if not low.endswith((".vue", ".ts", ".tsx", ".js", ".jsx")):
                continue
            seen_files.add(rel)
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            script = extract_vue_scripts(raw) if low.endswith(".vue") else raw
            imports = _imports_from_source(script)
            parser = parser_for_path(rel)
            source_bytes = script.encode("utf-8")
            api_calls = _walk_calls_ts(source_bytes, parser, rel)
            if not api_calls:
                for i, line in enumerate(script.splitlines(), start=1):
                    for m in API_CALL_FALLBACK_RE.finditer(line):
                        method = (m.group(1) or "GET").upper()
                        pth = m.group(2) or m.group(3) or m.group(4) or m.group(5)
                        if pth:
                            api_calls.append(
                                FrontendApiCall(method=method, path=pth, file_path=rel, line=i)
                            )

            components.append(ComponentUnit(file_path=rel, imports=imports, api_calls=api_calls))
            all_calls.extend(api_calls)
            routes.extend(_routes_from_text(script if "router" in low else raw, rel))

    return FrontendIndex(components=components, routes=routes, api_calls=all_calls)


def _import_graph(index: FrontendIndex) -> dict[str, set[str]]:
    """文件 → 直接 import 到的相对路径（已解析为 repo 内路径）。"""
    return {c.file_path: set(c.imports) for c in index.components}


def trace_frontend_impact(
    index: FrontendIndex,
    changed_files: set[str],
    repo_root: Path,
) -> dict:
    """从变更的 .vue/.ts 反查受影响路由与 API 调用。"""
    norm_changed = {p.replace("\\", "/") for p in changed_files}
    file_to_comp = {c.file_path: c for c in index.components}

    affected_files: set[str] = set()
    for ch in norm_changed:
        if ch in file_to_comp:
            affected_files.add(ch)

    # 反向：谁 import 了变更模块
    import_resolved: dict[str, set[str]] = {}
    for comp in index.components:
        resolved: set[str] = set()
        for spec in comp.imports:
            target = _resolve_import_to_file(repo_root, comp.file_path, spec)
            if target:
                resolved.add(target)
        import_resolved[comp.file_path] = resolved

    queue = list(affected_files)
    while queue:
        cur = queue.pop()
        for consumer, targets in import_resolved.items():
            if cur in targets and consumer not in affected_files:
                affected_files.add(consumer)
                queue.append(consumer)

    affected_routes: list[dict] = []
    for route in index.routes:
        comp = route.component_import
        if not comp:
            continue
        comp_norm = comp.replace("\\", "/")
        for af in affected_files:
            if comp_norm in af or af.endswith(comp_norm) or comp_norm.endswith(af):
                affected_routes.append(
                    {
                        "route_path": route.path,
                        "route_name": route.route_name,
                        "component_file": af,
                        "router_file": route.file_path,
                    }
                )
                break

    api_hits: list[dict] = []
    for comp in index.components:
        if comp.file_path not in affected_files:
            continue
        for call in comp.api_calls:
            api_hits.append(
                {
                    "method": call.method,
                    "path": call.path,
                    "file": call.file_path,
                    "line": call.line,
                }
            )

    return {
        "changed_frontend_files": sorted(norm_changed & affected_files),
        "affected_routes": affected_routes,
        "frontend_api_calls": api_hits,
        "trace_mode": "frontend_diff",
        "stats": {
            "affected_file_count": len(affected_files),
            "route_count": len(affected_routes),
            "api_call_count": len(api_hits),
        },
    }


def _normalize_http_path(raw: str) -> str:
    s = (raw or "").strip().split("?")[0]
    s = re.sub(r"\$\{[^}]+\}", "", s)
    if "://" in s:
        rest = s.split("://", 1)[1]
        slash = rest.find("/")
        s = rest[slash:] if slash >= 0 else f"/{rest}"
    if not s.startswith("/") and "/" in s:
        s = "/" + s.split("/", 1)[-1]
    elif not s.startswith("/"):
        s = f"/{s}"
    return (s.rstrip("/") or "/").lower()


def _paths_match(frontend_raw: str, backend_path: str) -> bool:
    fe = _normalize_http_path(frontend_raw)
    be = _normalize_http_path(backend_path)
    if fe == be:
        return True
    return fe.endswith(be) or be.endswith(fe)


def trace_frontend_for_backend_apis(
    index: FrontendIndex,
    backend_apis: list[dict],
    repo_root: Path,
) -> dict:
    """后端接口变更 / 影响面 → 反查本仓前端组件、路由与 fetch/axios 调用。"""
    targets: list[tuple[str, str, dict]] = []
    for api in backend_apis or []:
        path = str(api.get("path") or "")
        if not path:
            continue
        method = str(api.get("method") or "GET").upper()
        targets.append((method, _normalize_http_path(path), api))

    if not targets:
        return {
            "affected_routes": [],
            "frontend_api_calls": [],
            "affected_pages": [],
            "trace_mode": "backend_api",
            "stats": {"affected_file_count": 0, "route_count": 0, "api_call_count": 0},
        }

    api_hits: list[dict] = []
    affected_files: set[str] = set()
    for comp in index.components:
        for call in comp.api_calls:
            for method, norm_path, api in targets:
                if not _paths_match(call.path, norm_path):
                    continue
                if method != "GET" and call.method not in (method, "GET"):
                    continue
                affected_files.add(comp.file_path)
                api_hits.append(
                    {
                        "method": call.method,
                        "path": call.path,
                        "file": comp.file_path,
                        "line": call.line,
                        "backend_method": api.get("method"),
                        "backend_path": api.get("path"),
                        "backend_handler": api.get("handler"),
                    }
                )
                break

    affected_routes: list[dict] = []
    for route in index.routes:
        comp = (route.component_import or "").replace("\\", "/")
        for af in affected_files:
            if comp and (comp in af or af.endswith(comp)):
                affected_routes.append(
                    {
                        "route_path": route.path,
                        "route_name": route.route_name,
                        "component_file": af,
                        "router_file": route.file_path,
                    }
                )

    affected_pages: list[dict] = []
    for af in sorted(affected_files):
        if any(r.get("component_file") == af for r in affected_routes):
            continue
        apis = sorted(
            {
                str(h.get("backend_path") or "")
                for h in api_hits
                if h.get("file") == af and h.get("backend_path")
            }
        )
        affected_pages.append(
            {
                "route_path": "—",
                "route_name": Path(af).stem,
                "component_file": af,
                "router_file": "SPA / React",
                "linked_apis": apis,
            }
        )

    merged_routes = affected_routes + affected_pages
    return {
        "affected_routes": merged_routes,
        "frontend_api_calls": api_hits,
        "affected_pages": affected_pages,
        "trace_mode": "backend_api",
        "stats": {
            "affected_file_count": len(affected_files),
            "route_count": len(merged_routes),
            "api_call_count": len(api_hits),
        },
    }


def merge_frontend_impact(diff_impact: dict, backend_impact: dict) -> dict:
    """合并「前端 diff」与「后端 API 反查」结果。"""
    if not backend_impact.get("frontend_api_calls"):
        return diff_impact
    if not diff_impact.get("frontend_api_calls"):
        return {**diff_impact, **backend_impact, "trace_mode": "backend_api"}

    seen = {
        (r.get("file"), r.get("line"), r.get("backend_path"))
        for r in diff_impact.get("frontend_api_calls") or []
    }
    merged_calls = list(diff_impact.get("frontend_api_calls") or [])
    for row in backend_impact.get("frontend_api_calls") or []:
        key = (row.get("file"), row.get("line"), row.get("backend_path"))
        if key not in seen:
            seen.add(key)
            merged_calls.append(row)

    route_keys = {(r.get("route_path"), r.get("component_file")) for r in diff_impact.get("affected_routes") or []}
    merged_routes = list(diff_impact.get("affected_routes") or [])
    for r in backend_impact.get("affected_routes") or []:
        k = (r.get("route_path"), r.get("component_file"))
        if k not in route_keys:
            route_keys.add(k)
            merged_routes.append(r)

    return {
        **diff_impact,
        "affected_routes": merged_routes,
        "frontend_api_calls": merged_calls,
        "affected_pages": backend_impact.get("affected_pages") or [],
        "trace_mode": "frontend_diff+backend_api",
        "stats": {
            "affected_file_count": len({c.get("file") for c in merged_calls if c.get("file")}),
            "route_count": len(merged_routes),
            "api_call_count": len(merged_calls),
        },
    }