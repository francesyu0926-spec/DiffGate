"""跨仓 HTTP Client 扫描（Python httpx/requests + TS axios/fetch）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.parsers.treesitter_lang import parser_for_path
from app.parsers.vue_ts_index import API_CALL_FALLBACK_RE, _walk_calls_ts, SKIP_DIR

PY_HTTP_RE = re.compile(
    r"""
    (?:httpx|requests|aiohttp)\.(?:AsyncClient|Client)?\s*\(\s*\)|(?:httpx|requests)\.
    (get|post|put|patch|delete|head|options)\s*\(
    [\s\S]{0,400}?
    ['"]([^'"]+)['"]
    """,
    re.IGNORECASE | re.VERBOSE,
)
PY_CLIENT_METHOD_RE = re.compile(
    r"""client\.(get|post|put|patch|delete)\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
PY_SIMPLE_HTTP_RE = re.compile(
    r"""(?:httpx|requests)\.(get|post|put|patch|delete)\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)


@dataclass
class HttpClientHit:
    consumer_repo: str
    file_path: str
    line: int
    method: str
    url_or_path: str
    client_kind: str


def _scan_python_file(repo_key: str, path: Path, rel: str) -> list[HttpClientHit]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[HttpClientHit] = []
    for i, line in enumerate(text.splitlines(), start=1):
        for m in PY_CLIENT_METHOD_RE.finditer(line):
            hits.append(
                HttpClientHit(
                    consumer_repo=repo_key,
                    file_path=rel,
                    line=i,
                    method=m.group(1).upper(),
                    url_or_path=m.group(2),
                    client_kind="python-client",
                )
            )
        for m in PY_SIMPLE_HTTP_RE.finditer(line):
            hits.append(
                HttpClientHit(
                    consumer_repo=repo_key,
                    file_path=rel,
                    line=i,
                    method=m.group(1).upper(),
                    url_or_path=m.group(2),
                    client_kind="python-httpx/requests",
                )
            )
        for m in PY_HTTP_RE.finditer(line):
            method = (m.group(1) or "GET").upper()
            url = m.group(2)
            if url:
                hits.append(
                    HttpClientHit(
                        consumer_repo=repo_key,
                        file_path=rel,
                        line=i,
                        method=method,
                        url_or_path=url,
                        client_kind="python-httpx/requests",
                    )
                )
    return hits


def _scan_ts_file(repo_key: str, path: Path, rel: str) -> list[HttpClientHit]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    parser = parser_for_path(rel)
    hits: list[HttpClientHit] = []
    if parser:
        for call in _walk_calls_ts(raw.encode("utf-8"), parser, rel):
            hits.append(
                HttpClientHit(
                    consumer_repo=repo_key,
                    file_path=rel,
                    line=call.line,
                    method=call.method,
                    url_or_path=call.path,
                    client_kind="typescript",
                )
            )
    for i, line in enumerate(raw.splitlines(), start=1):
        for m in API_CALL_FALLBACK_RE.finditer(line):
            method = (m.group(1) or "GET").upper()
            pth = m.group(2) or m.group(3) or m.group(4)
            if pth:
                hits.append(
                    HttpClientHit(
                        consumer_repo=repo_key,
                        file_path=rel,
                        line=i,
                        method=method,
                        url_or_path=pth,
                        client_kind="typescript-regex",
                    )
                )
    return hits


def scan_repo_http_clients(repo_root: Path, repo_key: str, scan_root: str = ".") -> list[HttpClientHit]:
    root = (repo_root / scan_root).resolve() if scan_root not in (".", "") else repo_root.resolve()
    if not root.is_dir():
        root = repo_root.resolve()
    hits: list[HttpClientHit] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR for part in path.parts):
            continue
        rel = path.relative_to(repo_root.resolve()).as_posix()
        low = rel.lower()
        if low.endswith(".py"):
            hits.extend(_scan_python_file(repo_key, path, rel))
        elif low.endswith((".ts", ".tsx", ".js", ".jsx", ".vue")):
            if low.endswith(".vue"):
                from app.parsers.vue_ts_index import extract_vue_scripts

                try:
                    script = extract_vue_scripts(path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
                tmp = path.parent / f".__dg_{path.stem}.ts"
                try:
                    tmp.write_text(script, encoding="utf-8")
                    hits.extend(_scan_ts_file(repo_key, tmp, rel))
                finally:
                    tmp.unlink(missing_ok=True)
            else:
                hits.extend(_scan_ts_file(repo_key, path, rel))
    return hits


def _normalize_api_path(path: str) -> str:
    p = path.strip()
    if "://" in p:
        idx = p.find("/", p.find("://") + 3)
        p = p[idx:] if idx >= 0 else p
    if "?" in p:
        p = p.split("?", 1)[0]
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/") or "/"


def normalize_contract_path(path: str) -> str:
    """FastAPI `{user_id}` / 动态段归一为 `*`，便于 PROVIDES/CONSUMES 对齐。"""
    import re

    p = _normalize_api_path(path)
    p = re.sub(r"\{[^}/]+\}", "*", p)
    p = re.sub(r"\$\{[^}]+\}", "*", p)
    # 字面量数字段降级为通配（消费者常写具体 id）
    p = re.sub(r"/\d+(?=/|$)", "/*", p)
    p = re.sub(r"/+", "/", p)
    return p.rstrip("/") or "/"


def http_client_confidence(url_or_path: str) -> float:
    """AST 无法完全解析的动态 URL 使用较低置信度。"""
    raw = (url_or_path or "").strip()
    if not raw:
        return 0.6
    dynamic_markers = ("{", "}", "${", "%(", " + ", 'f"', 'f"', "{host}", "${")
    if any(m in raw for m in dynamic_markers):
        return 0.6
    if "://" in raw and _normalize_api_path(raw) in ("/", ""):
        return 0.6
    return 0.85


def match_consumers(
    hits: list[HttpClientHit],
    provider_api_paths: list[str],
) -> list[dict]:
    needles = {_normalize_api_path(p) for p in provider_api_paths if p}
    out: list[dict] = []
    seen: set[tuple] = set()
    for h in hits:
        norm = _normalize_api_path(h.url_or_path)
        matched = None
        for n in needles:
            if norm == n or norm.endswith(n) or n.endswith(norm):
                matched = n
                break
        if not matched:
            continue
        key = (h.consumer_repo, h.file_path, h.line, matched)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "consumer_repo": h.consumer_repo,
                "file": h.file_path,
                "line": h.line,
                "method": h.method,
                "client_path": h.url_or_path,
                "matched_api": matched,
                "client_kind": h.client_kind,
            }
        )
    return sorted(out, key=lambda x: (x["consumer_repo"], x["file"]))