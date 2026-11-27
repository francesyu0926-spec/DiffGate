"""Java / Spring Boot 静态索引（符号、路由、调用边 → 统一 RepoGraphIR）。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.adapters.protocol import IRCallEdge, IREndpoint, IRSymbol, RepoGraphIR
from app.config import get_settings

_SKIP_DIRS = frozenset({".git", "target", "build", "node_modules", "out", ".gradle"})
_TEST_PATH_MARKERS = ("/src/test/java/", "\\src\\test\\java\\", "src/test/java/")

_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;")
_CLASS = re.compile(r"^\s*(?:public\s+)?(?:abstract\s+)?class\s+(\w+)")
_INTERFACE = re.compile(r"^\s*public\s+interface\s+(\w+)")
_IMPLEMENTS = re.compile(r"\bimplements\s+([\w.<>,\s]+)")
_METHOD = re.compile(
    r"^\s*(?:public|protected|private)\s+"
    r"(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?"
    r"[\w<>,\[\]\s]+\s+(\w+)\s*\(",
)
_REQUEST_CLASS = re.compile(
    r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']*)["\']',
    re.I,
)
_REQUEST_CLASS2 = re.compile(
    r"@RequestMapping\s*\(\s*path\s*=\s*[\"']([^\"']*)[\"']",
    re.I,
)
_HTTP_MAPPING = re.compile(
    r"@(Get|Post|Put|Patch|Delete|Request)Mapping\s*\(",
    re.I,
)
_HTTP_PATH = re.compile(
    r'@(?:Get|Post|Put|Patch|Delete)Mapping\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?["\']([^"\']*)["\']',
    re.I,
)
_CALL = re.compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\(")
_LOMBOK_LINE = re.compile(r"^\s*@(?:Data|Getter|Setter|Builder|Value)\b")


def _java_uid(repo_id: str, file_path: str, qualname: str) -> str:
    return f"{repo_id}:{file_path}:{qualname}"


def _join_paths(base: str, sub: str) -> str:
    b = (base or "").strip().rstrip("/")
    s = (sub or "").strip()
    if not b:
        return "/" + s.lstrip("/") if s else "/"
    if not s:
        return b if b.startswith("/") else f"/{b}"
    if not b.startswith("/"):
        b = f"/{b}"
    if not s.startswith("/"):
        s = f"/{s}"
    return (b.rstrip("/") + s).replace("//", "/")


def _should_skip_file(rel: str) -> bool:
    norm = rel.replace("\\", "/").lower()
    if not norm.endswith(".java"):
        return True
    return any(m.lower() in norm for m in _TEST_PATH_MARKERS)


def _scan_java_files(root: Path, repo_dir: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if not root.is_dir():
        return rows
    for path in root.rglob("*.java"):
        if any(p in _SKIP_DIRS for p in path.parts):
            continue
        rel = path.relative_to(repo_dir.resolve()).as_posix()
        if _should_skip_file(rel):
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
    root = (repo_dir / scan_root.strip().lstrip("/")).resolve()
    symbols: list[IRSymbol] = []
    endpoints: list[IREndpoint] = []
    edges: list[IRCallEdge] = []
    interface_methods: dict[str, set[str]] = {}
    impl_by_iface: dict[str, list[str]] = {}

    for rel, text in _scan_java_files(root, repo_dir):
        pkg = ""
        class_name = ""
        class_base_path = ""
        methods_in_class: dict[str, int] = {}
        current_method = ""
        lines = text.splitlines()

        for i, line in enumerate(lines, start=1):
            pm = _PACKAGE.match(line)
            if pm:
                pkg = pm.group(1)
            cm = _CLASS.match(line)
            if cm:
                class_name = cm.group(1)
                class_base_path = ""
            im = _INTERFACE.match(line)
            if im:
                class_name = im.group(1)
                interface_methods.setdefault(class_name, set())
            if class_name and "implements" in line:
                for part in _IMPLEMENTS.findall(line):
                    for iface in re.split(r"[,\s]+", part.replace("<", " ").replace(">", " ")):
                        iface = iface.strip()
                        if iface:
                            impl_by_iface.setdefault(iface.split(".")[-1], []).append(class_name)

            rm = _REQUEST_CLASS.search(line) or _REQUEST_CLASS2.search(line)
            if rm and class_name:
                class_base_path = rm.group(1)

            if _HTTP_MAPPING.search(line) and class_name:
                path_m = _HTTP_PATH.search(line)
                sub_path = path_m.group(1) if path_m else ""
                method_m = re.search(
                    r"@(\w+)Mapping",
                    line,
                    re.I,
                )
                http_method = (method_m.group(1) if method_m else "Get").upper()
                if http_method == "REQUEST":
                    http_method = "GET"
                full_path = _join_paths(class_base_path, sub_path)
                qual = f"{pkg}.{class_name}#handler:L{i}" if pkg else f"{class_name}#handler:L{i}"
                uid = _java_uid(repo_id, rel, qual)
                endpoints.append(
                    IREndpoint(
                        method=http_method,
                        path=full_path,
                        symbol_uid=uid,
                        file_path=rel,
                        qualname=qual,
                    )
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
                        route_path=full_path,
                    )
                )

            mm = _METHOD.match(line)
            if mm and class_name and not line.strip().startswith("//"):
                meth = mm.group(1)
                if meth in ("class", "interface", "enum", "if", "for", "while", "switch"):
                    continue
                qual = f"{pkg}.{class_name}#{meth}" if pkg else f"{class_name}#{meth}"
                uid = _java_uid(repo_id, rel, qual)
                end_line = min(i + 80, len(lines))
                symbols.append(
                    IRSymbol(
                        uid=uid,
                        qualname=qual,
                        file_path=rel,
                        kind="method",
                        start_line=i,
                        end_line=end_line,
                    )
                )
                methods_in_class[meth] = i
                current_method = meth
                if class_name in interface_methods:
                    interface_methods[class_name].add(meth)

            for callee_owner, callee_meth in _CALL.findall(line):
                if not class_name or not current_method:
                    continue
                caller = f"{pkg}.{class_name}#{current_method}" if pkg else f"{class_name}#{current_method}"
                callee = f"{callee_owner}.{callee_meth}"
                edges.append(IRCallEdge(caller_qualname=caller, callee_qualname=callee))

        for iface, methods in interface_methods.items():
            for impl in impl_by_iface.get(iface, []):
                for meth in methods:
                    edges.append(
                        IRCallEdge(
                            caller_qualname=f"{iface}#{meth}",
                            callee_qualname=f"{impl}#{meth}",
                        )
                    )

    return RepoGraphIR(
        repo_id=repo_id,
        repo_full_name=repo_full_name,
        language="java",
        symbols=symbols,
        call_edges=edges,
        endpoints=endpoints,
        meta={
            "symbol_count": len(symbols),
            "edge_count": len(edges),
            "api_count": len(endpoints),
            "index_mode": "regex_spring",
        },
    )


def _index_from_cli_jar(repo_dir: Path, scan_root: str) -> dict | None:
    jar = (get_settings().java_analyzer_jar or "").strip()
    if not jar or not Path(jar).is_file():
        return None
    try:
        proc = subprocess.run(
            [
                "java",
                "-jar",
                jar,
                "--repo",
                str(repo_dir),
                "--scan-root",
                scan_root or "src/main/java",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        import json

        return json.loads(proc.stdout)
    except Exception:
        return None


def index_java(
    *,
    repo_id: str,
    repo_full_name: str,
    repo_dir: Path,
    scan_root: str,
) -> RepoGraphIR:
    """优先可选 diffgate-java-analyzer.jar；否则内置 Spring 正则索引。"""
    payload = _index_from_cli_jar(repo_dir, scan_root)
    if isinstance(payload, dict) and payload.get("symbols"):
        symbols = [IRSymbol(**s) for s in payload.get("symbols", [])]
        endpoints = [IREndpoint(**e) for e in payload.get("endpoints", [])]
        edges = [IRCallEdge(**e) for e in payload.get("call_edges", [])]
        return RepoGraphIR(
            repo_id=repo_id,
            repo_full_name=repo_full_name,
            language="java",
            symbols=symbols,
            call_edges=edges,
            endpoints=endpoints,
            meta={**(payload.get("meta") or {}), "index_mode": "java_analyzer_jar"},
        )
    return _index_from_source(
        repo_id=repo_id,
        repo_full_name=repo_full_name,
        repo_dir=repo_dir,
        scan_root=scan_root or "src/main/java",
    )