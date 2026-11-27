"""前端 API 契约：前缀拼接、路径归一化与置信度。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.parsers.http_client_scan import normalize_contract_path
from app.parsers.vue_ts_index import FrontendIndex

_RE_TEMPLATE = re.compile(r"\$\{[^}]+\}")
_ENV_KEY_RE = re.compile(
    r"^\s*(?:VITE_|NEXT_PUBLIC_|NUXT_PUBLIC_)?(?:API_BASE|API_URL|BASE_URL)\s*=\s*['\"]?([^'\"\s#]+)",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class ApiPathAlign:
    prefix: str = ""
    strip_prefix: str = ""


def read_env_api_base(repo_root: Path) -> str:
    """读取前端 .env / .env.production 中的 API Base URL。"""
    repo_root = repo_root.resolve()
    for name in (".env.production", ".env.local", ".env"):
        path = repo_root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _ENV_KEY_RE.finditer(text):
            val = (m.group(1) or "").strip().rstrip("/")
            if val and not val.startswith("#"):
                if "://" in val:
                    rest = val.split("://", 1)[1]
                    slash = rest.find("/")
                    return rest[slash:] if slash >= 0 else ""
                return val if val.startswith("/") else f"/{val}"
    return ""


def resolve_api_path_align(repo, repo_root: Path | None = None) -> ApiPathAlign:
    """合并手工前缀、网关 strip_prefix 与 .env 默认值。"""
    raw_prefix = (getattr(repo, "api_base_prefix", None) or "").strip()
    strip = (getattr(repo, "api_strip_prefix", None) or "").strip()
    prefix = raw_prefix
    if raw_prefix.startswith("{"):
        try:
            obj = json.loads(raw_prefix)
            if isinstance(obj, dict):
                prefix = str(obj.get("prefix") or obj.get("api_base_prefix") or "").strip()
                strip = strip or str(obj.get("strip_prefix") or "").strip()
        except json.JSONDecodeError:
            prefix = raw_prefix
    if not prefix and repo_root is not None:
        prefix = read_env_api_base(repo_root) or ""
    return ApiPathAlign(prefix=prefix, strip_prefix=strip)


def normalize_plus_concatenated_path(raw: str) -> str:
    """'/jobs/' + id + '/graph' → /jobs/*/graph"""
    raw = (raw or "").split("?")[0].strip()
    if "+" not in raw:
        return raw
    literals = re.findall(r"['\"`]([^'\"`]+)['\"`]", raw)
    if not literals:
        return raw
    if len(literals) == 1:
        return literals[0] + ("/*" if "+" in raw else "")
    first = literals[0].rstrip("/")
    last = literals[-1]
    if not last.startswith("/"):
        last = "/" + last
    middle = "/*" if raw.count("+") >= 1 else ""
    return re.sub(r"/+", "/", f"{first}{middle}{last}")


def apply_strip_prefix(path: str, strip_prefix: str) -> str:
    p = (path or "").strip()
    sp = (strip_prefix or "").strip().rstrip("/")
    if not sp or not p.startswith(sp):
        return p
    rest = p[len(sp) :] or "/"
    return rest if rest.startswith("/") else f"/{rest}"


def apply_api_base_prefix(raw_path: str, prefix: str) -> str:
    p = (raw_path or "").strip().split("?")[0]
    if not p:
        return "/"
    if p.startswith("http://") or p.startswith("https://"):
        return p
    base = (prefix or "").strip().rstrip("/")
    if not base:
        return p if p.startswith("/") else f"/{p}"
    if p.startswith(base + "/") or p == base:
        return p if p.startswith("/") else f"/{p}"
    if p.startswith("/"):
        return f"{base}{p}"
    return f"{base}/{p.lstrip('/')}"


def normalize_frontend_api_path(
    raw_path: str,
    *,
    api_base_prefix: str = "",
    strip_prefix: str = "",
    align: ApiPathAlign | None = None,
) -> str:
    raw = (raw_path or "").strip()
    if "+" in raw:
        raw = normalize_plus_concatenated_path(raw)
    al = align or ApiPathAlign(prefix=api_base_prefix, strip_prefix=strip_prefix)
    p = apply_strip_prefix(raw.split("?")[0], al.strip_prefix)
    p = apply_api_base_prefix(p, al.prefix)
    if "://" in p:
        rest = p.split("://", 1)[1]
        slash = rest.find("/")
        p = rest[slash:] if slash >= 0 else f"/{rest}"
    p = _RE_TEMPLATE.sub("*", p)
    p = re.sub(r"`[^`]*\$\{[^}]+\}[^`]*`", "*", p)
    p = normalize_contract_path(p)
    return p or "/"


def frontend_call_confidence(raw_path: str) -> float:
    raw = (raw_path or "").strip()
    if not raw:
        return 0.6
    markers = ("${", "{", " + ", "`", "%(", "config.", "import.meta", "process.env")
    if any(m in raw for m in markers):
        return 0.6
    if not raw.startswith("/") and "://" not in raw:
        return 0.6
    return 0.9


def expand_frontend_api_calls(
    index: FrontendIndex,
    *,
    api_base_prefix: str = "",
    strip_prefix: str = "",
    align: ApiPathAlign | None = None,
) -> list[dict]:
    al = align or ApiPathAlign(prefix=api_base_prefix, strip_prefix=strip_prefix)
    rows: list[dict] = []
    for call in index.api_calls:
        norm = normalize_frontend_api_path(call.path, align=al)
        conf = frontend_call_confidence(call.path)
        rows.append(
            {
                "method": (call.method or "GET").upper(),
                "path": call.path,
                "path_norm": norm,
                "file": call.file_path,
                "line": call.line,
                "confidence": conf,
                "dynamic": conf < 0.7,
            }
        )
    return rows


def contract_keys_from_calls(calls: list[dict]) -> list[str]:
    from app.graph.neo4j_contracts import contract_key_http

    keys: list[str] = []
    for c in calls:
        method = (c.get("method") or "GET").upper()
        path = c.get("path_norm") or c.get("path") or "/"
        keys.append(contract_key_http(method, path))
    return keys