"""跨微服务：在其他已接入仓库中扫描 HTTP Client 消费方。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Repository
from app.parsers.http_client_scan import match_consumers, scan_repo_http_clients


def _repo_dir(full_name: str) -> Path:
    safe = full_name.replace("/", "_")
    return (Path(get_settings().repo_clone_root) / safe).resolve()


def find_cross_repo_consumers(
    db: Session,
    *,
    provider_repo: str,
    provider_api_paths: list[str],
    extra_paths: list[str] | None = None,
) -> dict:
    """扫描除提供方外的 enabled 仓库 clone（若存在）。"""
    paths = list(provider_api_paths)
    if extra_paths:
        paths.extend(extra_paths)
    paths = [p for p in paths if p]
    if not paths:
        return {"consumers": [], "scanned_repos": [], "match_count": 0}

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
    return {
        "consumers": consumers,
        "scanned_repos": scanned,
        "match_count": len(consumers),
        "provider_repo": provider_repo,
        "needle_paths": sorted({_normalize(p) for p in paths}),
    }


def _normalize(p: str) -> str:
    from app.parsers.http_client_scan import _normalize_api_path

    return _normalize_api_path(p)