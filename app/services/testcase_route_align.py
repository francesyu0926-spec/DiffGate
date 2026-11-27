"""测试用例中提取的 path 与业务仓库 api_base_prefix 对齐。"""

from __future__ import annotations

import re

from app.db.models import Repository
from app.graph.neo4j_contracts import contract_key_http
from app.parsers.frontend_contract import apply_api_base_prefix, apply_strip_prefix
from app.parsers.http_client_scan import _normalize_api_path, normalize_contract_path
from app.services.testcase_fingerprint import contract_key_to_fingerprint

_ENV_TOKEN = re.compile(r"\{\{[^}]+\}\}|\$\{[^}]+\}|%\([^)]+\)s")
_SCHEME = re.compile(r"^https?://", re.I)


def strip_test_url_tokens(raw: str) -> str:
    s = (raw or "").strip().strip("\"'")
    s = _ENV_TOKEN.sub("", s)
    if _SCHEME.search(s):
        idx = s.find("/", s.find("://") + 3)
        s = s[idx:] if idx >= 0 else "/"
    return _normalize_api_path(s.split("?")[0])


def align_test_route(
    raw_url: str,
    method: str,
    repo: Repository | None,
) -> tuple[str, str, str]:
    """返回 (normalized_route, contract_key, display_fingerprint)。"""
    path = strip_test_url_tokens(raw_url)
    if repo is not None:
        path = apply_strip_prefix(path, repo.api_strip_prefix or "")
        path = apply_api_base_prefix(path, repo.api_base_prefix or "")
    path = normalize_contract_path(path)
    m = (method or "GET").upper()
    ck = contract_key_http(m, path)
    fp = contract_key_to_fingerprint(ck)
    return path, ck, fp