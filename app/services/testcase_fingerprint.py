"""受影响 API 指纹 ↔ AST Contract Key 互转（与 Neo4j / 分析任务一致）。"""

from __future__ import annotations

import re

from app.graph.neo4j_contracts import contract_key_http
from app.parsers.http_client_scan import normalize_contract_path

_FP_RE = re.compile(r"^(?:(HTTP):)?([A-Z]+):(/.+)$", re.I)


def contract_key_to_fingerprint(contract_key: str) -> str:
    ck = (contract_key or "").strip()
    if ck.upper().startswith("HTTP:"):
        rest = ck.split(":", 2)
        if len(rest) == 3:
            return f"{rest[1].upper()}:{rest[2]}"
    return ck


def fingerprint_to_contract_key(fingerprint: str) -> str:
    fp = (fingerprint or "").strip()
    m = _FP_RE.match(fp)
    if m:
        method = m.group(2).upper()
        path = normalize_contract_path(m.group(3))
        return contract_key_http(method, path)
    if fp.upper().startswith("HTTP:"):
        parts = fp.split(":", 2)
        if len(parts) == 3:
            return contract_key_http(parts[1], parts[2])
    if " " in fp:
        method, path = fp.split(" ", 1)
        return contract_key_http(method, path)
    return contract_key_http("GET", fp or "/")


def contract_keys_from_affected_apis(affected: dict | None) -> list[str]:
    keys: list[str] = []
    for api in (affected or {}).get("apis") or []:
        if not isinstance(api, dict):
            continue
        method = str(api.get("method") or "GET").upper()
        path = str(api.get("path") or "/")
        keys.append(contract_key_http(method, path))
    return sorted(set(keys))


def fingerprints_from_affected_apis(affected: dict | None) -> list[str]:
    return [contract_key_to_fingerprint(k) for k in contract_keys_from_affected_apis(affected)]