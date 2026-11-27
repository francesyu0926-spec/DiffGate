"""仓库接入槽位：(clone_url, scan_root, repo_type) 唯一。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Repository


def normalize_scan_root(scan_root: str | None) -> str:
    s = (scan_root or ".").strip() or "."
    return s.replace("\\", "/")


def find_repo_slot(
    db: Session, *, clone_url: str, scan_root: str, repo_type: str
) -> Repository | None:
    root = normalize_scan_root(scan_root)
    url = clone_url.strip()
    rows = db.scalars(
        select(Repository).where(
            Repository.clone_url == url,
            Repository.scan_root == root,
            Repository.repo_type == repo_type,
        )
    ).all()
    return rows[0] if rows else None


def find_repos_by_clone_url(db: Session, clone_url: str) -> list[Repository]:
    url = clone_url.strip()
    return list(db.scalars(select(Repository).where(Repository.clone_url == url)).all())


def repos_matching_platform_name(db: Session, *, clone_url: str, platform_full_name: str) -> list[Repository]:
    by_url = find_repos_by_clone_url(db, clone_url)
    if by_url:
        return [r for r in by_url if r.enabled and r.webhook_enabled]
    pf = platform_full_name.strip()
    if not pf:
        return []
    return list(
        db.scalars(
            select(Repository).where(
                Repository.enabled.is_(True),
                Repository.webhook_enabled.is_(True),
                Repository.full_name == pf,
            )
        ).all()
    )


def suggested_full_name_suffix(scan_root: str) -> str:
    root = normalize_scan_root(scan_root)
    if root in (".", ""):
        return ""
    seg = root.split("/")[-1] or root
    return f" ({seg})"


def build_suggested_full_name(base: str, scan_root: str, clone_url: str, db: Session) -> str:
    base = (base or "").strip() or "project"
    if not find_repos_by_clone_url(db, clone_url):
        return base
    suffix = suggested_full_name_suffix(scan_root)
    if suffix and not base.endswith(suffix):
        return f"{base}{suffix}"
    return base