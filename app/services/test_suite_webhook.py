"""测试仓库 Push → 用例集索引异步保鲜。"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from urllib.parse import urlparse

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Repository, TestSuite
from app.db.session import SessionLocal
from app.services.test_suite_sync import sync_test_suite

logger = logging.getLogger(__name__)


def _norm_git_remote(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    if u.startswith("git@"):
        # git@github.com:org/repo → github.com/org/repo
        host, path = u.split(":", 1) if ":" in u else ("", u)
        host = host.replace("git@", "")
        return f"{host.lower()}/{path.strip('/')}".lower()
    parsed = urlparse(u)
    if parsed.netloc:
        return f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}".lower()
    return u.lower()


def _urls_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    na, nb = _norm_git_remote(a), _norm_git_remote(b)
    return na == nb or na.endswith(nb) or nb.endswith(na)


def _branch_name(ref: str) -> str:
    r = (ref or "").strip()
    if r.startswith("refs/heads/"):
        return r.removeprefix("refs/heads/")
    return r


def find_test_suites_for_push(
    db: Session,
    *,
    clone_url: str,
    extra_clone_urls: list[str] | None,
    ref: str,
) -> list[TestSuite]:
    urls = [clone_url, *(extra_clone_urls or [])]
    branch = _branch_name(ref)
    rows = db.scalars(
        select(TestSuite).where(TestSuite.enabled.is_(True), TestSuite.source_type == "git")
    ).all()
    repo_rows = list(db.scalars(select(Repository)).all())
    repo_by_id = {r.id: r for r in repo_rows}
    matched: list[TestSuite] = []

    for suite in rows:
        configured_branch = (suite.git_branch or "main").strip() or "main"
        if branch and configured_branch not in (branch, "*"):
            continue

        candidates: list[str] = []
        if (suite.git_url or "").strip():
            candidates.append(suite.git_url.strip())
        reuse = (suite.git_reuse_repository_id or "").strip()
        if reuse and reuse in repo_by_id:
            candidates.append(repo_by_id[reuse].clone_url or "")
        for repo in repo_rows:
            if repo.test_suite_id == suite.slug and repo.clone_url:
                candidates.append(repo.clone_url)

        hit = False
        for cu in urls:
            if any(_urls_match(cu, c) for c in candidates if c):
                hit = True
                break
        if hit:
            matched.append(suite)
    return matched


def push_touches_case_path(changed_paths: list[str] | None, case_path: str | None) -> bool:
    if not changed_paths:
        return True
    root = (case_path or ".").strip().strip("/")
    if not root or root == ".":
        return any(p.endswith((".yaml", ".yml", ".py")) for p in changed_paths)
    prefix = PurePosixPath(root).as_posix()
    for p in changed_paths:
        norm = p.replace("\\", "/").strip("/")
        if norm == prefix or norm.startswith(prefix + "/"):
            return True
    return False


def sync_test_suite_by_id(suite_id: str) -> dict:
    db = SessionLocal()
    try:
        row = db.get(TestSuite, suite_id)
        if not row:
            return {"ok": False, "error": "suite not found"}
        report = sync_test_suite(db, row)
        db.commit()
        if isinstance(report, dict):
            return {"ok": True, **report}
        return {"ok": True, "message": str(report)}
    except Exception as exc:
        db.rollback()
        logger.exception("test suite index sync failed suite_id=%s", suite_id)
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()


def enqueue_test_suite_sync_on_push(
    db: Session,
    background_tasks,
    *,
    clone_url: str,
    extra_clone_urls: list[str] | None,
    ref: str,
    changed_paths: list[str] | None,
) -> list[str]:
    suites = find_test_suites_for_push(
        db,
        clone_url=clone_url,
        extra_clone_urls=extra_clone_urls,
        ref=ref,
    )
    queued: list[str] = []
    for suite in suites:
        if not push_touches_case_path(changed_paths, suite.case_path):
            continue
        background_tasks.add_task(sync_test_suite_by_id, suite.id)
        queued.append(suite.slug)
    return queued