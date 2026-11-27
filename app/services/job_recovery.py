"""恢复 debouncing / pending 僵尸任务（进程重启或 BackgroundTasks 失效）。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db.models import AnalysisJob, Repository
from app.db.session import SessionLocal
from app.services.analysis_runner import schedule_analyze_merge
from app.services.job_execution_state import mark_cancelled
from app.services.probe_timeout import fuse_stale_probe_returns
from app.services.webhook_debounce import branch_key, supersede_branch_stale_jobs

logger = logging.getLogger(__name__)


def _clone_url_for_job(db, job: AnalysisJob) -> str | None:
    rec = db.scalar(select(Repository).where(Repository.full_name == job.repo_full_name))
    if rec and rec.clone_url:
        return rec.clone_url
    meta = job.job_metadata or {}
    return meta.get("clone_url")


def _dispatch_job(db, job: AnalysisJob, clone_url: str) -> bool:
    schedule_analyze_merge(
        background_tasks=None,
        job_id=job.id,
        provider=job.provider,
        repo_full_name=job.repo_full_name,
        clone_url=clone_url,
        base_sha=job.base_sha,
        head_sha=job.head_sha,
        ref=job.ref,
    )
    return True


def recover_stuck_jobs(*, max_pending: int = 50) -> dict:
    """启动时调用：超时 debouncing → pending 并重投；pending 仅重投分析。"""
    settings = get_settings()
    window = max(0, int(settings.webhook_debounce_seconds))
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        seconds=max(window + 5, 30)
    )
    db = SessionLocal()
    recovered_pending = 0
    recovered_debouncing = 0
    skipped = 0
    try:
        stmt = (
            select(AnalysisJob)
            .where(AnalysisJob.status.in_(("pending", "debouncing")))
            .order_by(AnalysisJob.created_at.asc())
            .limit(max_pending * 2)
        )
        rows = list(db.scalars(stmt).all())
        # 每个分支只恢复最新一条，其余 superseded
        latest_by_branch: dict[str, AnalysisJob] = {}
        for job in sorted(rows, key=lambda j: j.created_at or datetime.min):
            if job.status not in ("pending", "debouncing"):
                continue
            latest_by_branch[branch_key(job.repo_full_name, job.ref)] = job

        for job in rows:
            clone_url = _clone_url_for_job(db, job)
            if not clone_url:
                skipped += 1
                logger.warning("recover skip job %s: no clone_url", job.id)
                continue

            if job.status == "debouncing":
                updated = job.updated_at or job.created_at
                if updated and updated > cutoff:
                    continue
                job.status = "pending"
                db.commit()
                recovered_debouncing += 1

            if job.status != "pending":
                continue
            bk = branch_key(job.repo_full_name, job.ref)
            if latest_by_branch.get(bk) is not job:
                job.status = "superseded"
                job.error_message = "被同分支更新的 Push 取代（启动恢复合并）"
                db.commit()
                continue
            supersede_branch_stale_jobs(
                db, repo_full_name=job.repo_full_name, ref=job.ref, keep_job_id=job.id
            )
            if recovered_pending >= max_pending:
                break
            _dispatch_job(db, job, clone_url)
            recovered_pending += 1
            logger.info("recover dispatched job %s (%s)", job.id, job.head_sha[:8])
    finally:
        db.close()

    probe_timeouts = fuse_stale_probe_returns()

    return {
        "recovered_pending": recovered_pending,
        "recovered_debouncing": recovered_debouncing,
        "skipped_no_clone_url": skipped,
        "probe_timeouts": probe_timeouts,
    }