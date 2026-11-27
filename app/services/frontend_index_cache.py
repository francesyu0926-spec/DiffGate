"""前端 AST 索引缓存（全量索引后供跨仓契约匹配）。"""

from __future__ import annotations

from app.graph import local_cache
from app.parsers.frontend_contract import expand_frontend_api_calls, resolve_api_path_align
from app.parsers.vue_ts_index import FrontendIndex, scan_frontend_repo


def cache_key(repo_id: str) -> str:
    return f"fe_index/{repo_id}.json"


def save_frontend_index(
    repo_id: str,
    index: FrontendIndex,
    *,
    api_base_prefix: str = "",
    align=None,
    repo=None,
    repo_root=None,
) -> dict:
    al = align or (resolve_api_path_align(repo, repo_root) if repo is not None else None)
    payload = index.to_dict()
    if al is not None:
        payload["api_calls_norm"] = expand_frontend_api_calls(index, align=al)
        payload["api_base_prefix"] = al.prefix
        payload["api_strip_prefix"] = al.strip_prefix
    else:
        payload["api_calls_norm"] = expand_frontend_api_calls(index, api_base_prefix=api_base_prefix)
        payload["api_base_prefix"] = api_base_prefix
    local_cache.write_json(cache_key(repo_id), payload)
    return payload


def load_frontend_index(repo_id: str) -> dict | None:
    return local_cache.read_json(cache_key(repo_id))


def scan_and_cache_frontend(
    repo_root,
    repo_id: str,
    *,
    scan_root: str = ".",
    api_base_prefix: str = "",
    repo=None,
) -> dict:
    roots = tuple(s.strip() for s in (scan_root or ".").split(",") if s.strip()) or (".",)
    if len(roots) == 1 and roots[0] == ".":
        roots = ("src", "web", "frontend", ".")
    index = scan_frontend_repo(repo_root, scan_roots=roots)
    if repo is not None:
        return save_frontend_index(repo_id, index, repo=repo, repo_root=repo_root)
    return save_frontend_index(repo_id, index, api_base_prefix=api_base_prefix)