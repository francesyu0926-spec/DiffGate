"""Webhook 五步精准分发：归一匹配 → changed_files → scan_root 过滤 → 建任务 → 取代旧任务。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnalysisJob, Repository
from app.services.clone_url_normalize import (
    clone_url_match_key,
    clone_url_repo_slug,
    collect_incoming_clone_keys,
    record_matches_platform_repo,
)
from app.services.gitlab_private import webhook_core_fingerprint
from app.services.repository_uniqueness import normalize_scan_root
from app.services.webhook_debounce import register_debounced_analysis
from app.services.webhook_scan_filter import path_filter_skip_reason, repo_hit_by_scan_root

logger = logging.getLogger(__name__)


def find_webhook_targets(
    db: Session,
    *,
    clone_url: str,
    platform_full_name: str,
    extra_clone_urls: list[str] | None = None,
) -> list[Repository]:
    """第 1 步：所有 enabled + webhook_enabled 且 URL/平台名匹配的记录。"""
    incoming_keys, incoming_slugs, incoming_fps = collect_incoming_clone_keys(
        clone_url, *(extra_clone_urls or [])
    )
    if platform_full_name.strip():
        incoming_slugs.add(platform_full_name.strip().lower())
    pf = platform_full_name.strip()
    rows = db.scalars(
        select(Repository).where(
            Repository.enabled.is_(True),
            Repository.webhook_enabled.is_(True),
        )
    ).all()
    out: list[Repository] = []
    seen: set[str] = set()
    for repo in rows:
        key = clone_url_match_key(repo.clone_url)
        slug = clone_url_repo_slug(repo.clone_url)
        by_url = bool(key and key in incoming_keys)
        by_slug = bool(slug and slug in incoming_slugs)
        by_fp = bool(
            (fp := webhook_core_fingerprint(repo.clone_url)) and fp in incoming_fps
        )
        by_name = record_matches_platform_repo(repo.full_name, pf) if pf else False
        if not by_url and not by_slug and not by_fp and not by_name:
            continue
        if repo.id in seen:
            continue
        seen.add(repo.id)
        out.append(repo)
    return out


def _linked_repo_set(repo: Repository) -> set[str]:
    return set(repo.linked_repo_ids or [])


def _correlated_batch_id(hit_repos: list[Repository]) -> str | None:
    if len(hit_repos) < 2:
        return None
    linked = any(_linked_repo_set(r) for r in hit_repos)
    multi_root = len({normalize_scan_root(r.scan_root) for r in hit_repos}) >= 2
    if linked or multi_root:
        return str(uuid.uuid4())
    return None


def _enqueue_job(
    db: Session,
    background_tasks: BackgroundTasks,
    *,
    provider: str,
    repo: Repository,
    clone_url: str,
    base_sha: str,
    head_sha: str,
    ref: str,
    job_metadata: dict | None,
    correlated_batch_id: str | None,
) -> tuple[str, str | None]:
    job_id = str(uuid.uuid4())
    meta = dict(job_metadata or {})
    if correlated_batch_id:
        meta["correlated_batch_id"] = correlated_batch_id
    meta["scan_root"] = normalize_scan_root(repo.scan_root)
    meta["repository_id"] = repo.id
    job = AnalysisJob(
        id=job_id,
        provider=provider,
        repo_full_name=repo.full_name,
        ref=ref,
        base_sha=base_sha,
        head_sha=head_sha,
        status="pending",
        job_metadata=meta,
    )
    db.add(job)
    db.commit()
    reg = register_debounced_analysis(
        db=db,
        background_tasks=background_tasks,
        job=job,
        clone_url=clone_url,
    )
    return job_id, reg.get("task_id")


def dispatch_webhook_for_repos(
    db: Session,
    background_tasks: BackgroundTasks,
    *,
    provider: str,
    platform_full_name: str,
    clone_url: str,
    base_sha: str,
    head_sha: str,
    ref: str,
    job_metadata: dict | None,
    changed_paths: list[str] | None,
    extra_clone_urls: list[str] | None = None,
) -> dict[str, Any]:
    targets = find_webhook_targets(
        db,
        clone_url=clone_url,
        platform_full_name=platform_full_name,
        extra_clone_urls=extra_clone_urls,
    )
    if not targets:
        logger.info(
            "webhook_no_matching_repo provider=%s platform=%s clone_url=%s",
            provider,
            platform_full_name,
            clone_url,
        )
        return {
            "ok": True,
            "ignored": "no_webhook_enabled_repositories",
            "message": "未匹配到启用 Webhook 的仓库记录",
        }

    if changed_paths is None:
        hit_repos = list(targets)
        skipped = []
    else:
        files = list(changed_paths)
        hit_repos = []
        skipped = []
        for repo in targets:
            scan_root = normalize_scan_root(repo.scan_root)
            if repo_hit_by_scan_root(files, scan_root):
                hit_repos.append(repo)
            else:
                reason = path_filter_skip_reason(files, scan_root)
                logger.info(
                    "%s repo=%s scan_root=%s changed_files=%s",
                    reason,
                    repo.full_name,
                    scan_root,
                    len(files),
                )
                skipped.append(
                    {
                        "repo_full_name": repo.full_name,
                        "scan_root": scan_root,
                        "reason": reason,
                    }
                )

    if not hit_repos:
        return {
            "ok": True,
            "ignored": "all_skipped_by_path_filter",
            "skipped": skipped,
            "message": "变更未命中任何仓库 scan_root",
        }

    batch_id = _correlated_batch_id(hit_repos)
    job_ids: list[str] = []
    celery_ids: list[str] = []
    for repo in hit_repos:
        job_id, task_id = _enqueue_job(
            db,
            background_tasks,
            provider=provider,
            repo=repo,
            clone_url=clone_url,
            base_sha=base_sha,
            head_sha=head_sha,
            ref=ref,
            job_metadata=job_metadata,
            correlated_batch_id=batch_id,
        )
        job_ids.append(job_id)
        if task_id:
            celery_ids.append(task_id)

    out: dict[str, Any] = {
        "ok": True,
        "job_ids": job_ids,
        "matched_repositories": [r.full_name for r in hit_repos],
    }
    if len(job_ids) == 1:
        out["job_id"] = job_ids[0]
    if batch_id:
        out["correlated_batch_id"] = batch_id
    if celery_ids:
        out["celery_task_id"] = celery_ids[0]
    if skipped:
        out["skipped"] = skipped
    return out