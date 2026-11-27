"""跨微服务：在其他已接入仓库中扫描 HTTP Client 消费方。"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Repository
from app.parsers.http_client_scan import match_consumers, scan_repo_http_clients
from app.graph.stores import Neo4jCallGraphStore


def _repo_dir(full_name: str) -> Path:
    safe = full_name.replace("/", "_")
    return (Path(get_settings().repo_clone_root) / safe).resolve()


def find_cross_repo_consumers(
    db: Session,
    *,
    provider_repo: str,
    provider_api_paths: list[str],
    extra_paths: list[str] | None = None,
    provider_repo_id: str | None = None,
) -> dict:
    """扫描除提供方外的 enabled 仓库 clone（若存在）。"""
    paths = list(provider_api_paths)
    if extra_paths:
        paths.extend(extra_paths)
    paths = [p for p in paths if p]
    if not paths:
        return {"consumers": [], "scanned_repos": [], "match_count": 0}

    provider_rec = None
    if provider_repo_id:
        provider_rec = db.get(Repository, provider_repo_id)
    if not provider_rec:
        provider_rec = db.scalar(select(Repository).where(Repository.full_name == provider_repo))

    linked_ids = list(provider_rec.linked_repo_ids or []) if provider_rec else []
    if linked_ids:
        repos = list(
            db.scalars(
                select(Repository).where(
                    Repository.enabled.is_(True),
                    Repository.id.in_(linked_ids),
                )
            ).all()
        )
    else:
        repos = list(
            db.scalars(
                select(Repository).where(Repository.enabled.is_(True), Repository.full_name != provider_repo)
            ).all()
        )
    scanned: list[str] = []
    all_hits = []
    for repo in repos:
        root = _repo_dir(repo.full_name)
        if not root.is_dir():
            continue
        scan_root = (repo.scan_root or ".").strip() or "."
        hits = scan_repo_http_clients(root, repo.full_name, scan_root=scan_root)
        if hits:
            all_hits.extend(hits)
        scanned.append(repo.full_name)

    consumers = match_consumers(all_hits, paths)
    graph_consumers: list[dict] = []
    settings = get_settings()
    if settings.use_neo4j:
        try:
            store = Neo4jCallGraphStore()
            try:
                graph_consumers = store.find_consumers_for_paths(paths, exclude_repo=provider_repo)
            finally:
                store.close()
        except Exception:
            graph_consumers = []

    merged = {json.dumps(c, sort_keys=True): c for c in consumers if isinstance(c, dict)}
    for row in graph_consumers:
        key = json.dumps(
            {
                "consumer_repo": row.get("consumer_repo"),
                "file_path": row.get("file"),
                "line": row.get("line"),
                "url_or_path": row.get("url_or_path"),
            },
            sort_keys=True,
        )
        if key not in merged:
            merged[key] = {
                "consumer_repo": row.get("consumer_repo"),
                "file_path": row.get("file"),
                "line": row.get("line"),
                "method": row.get("method") or "GET",
                "url_or_path": row.get("url_or_path"),
                "provider_repo": row.get("provider_repo") or provider_repo,
                "source": "neo4j",
            }
    final = list(merged.values())
    return {
        "consumers": final,
        "scanned_repos": scanned,
        "match_count": len(final),
        "provider_repo": provider_repo,
        "needle_paths": sorted({_normalize(p) for p in paths}),
        "graph_match_count": len(graph_consumers),
    }


def _normalize(p: str) -> str:
    from app.parsers.http_client_scan import _normalize_api_path

    return _normalize_api_path(p)