"""Webhook 防抖：同分支短时间多次 push 仅保留最新 Commit 任务。"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AnalysisJob
from app.db.session import SessionLocal
from app.services.analysis_runner import schedule_analyze_merge
from app.services.job_execution_state import mark_cancelled

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_pending: dict[str, _Slot] = {}


@dataclass
class _Slot:
    job_id: str
    head_sha: str
    timer: threading.Timer


def branch_key(repo_full_name: str, ref: str) -> str:
    branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
    return f"{repo_full_name}::{branch}"


_branch_key = branch_key


def _job_pr_number(job: AnalysisJob) -> int | None:
    meta = job.job_metadata or {}
    raw = meta.get("pr_number")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _same_analysis_stream(a: AnalysisJob, b: AnalysisJob) -> bool:
    """同仓库 + 同分支，或同 MR pr_number。"""
    if a.repo_full_name != b.repo_full_name:
        return False
    pra, prb = _job_pr_number(a), _job_pr_number(b)
    if pra is not None and prb is not None:
        return pra == prb
    return branch_key(a.repo_full_name, a.ref) == branch_key(b.repo_full_name, b.ref)


def supersede_branch_stale_jobs(db: Session, *, repo_full_name: str, ref: str, keep_job_id: str) -> int:
    """同分支/MR 上除 keep_job_id 外的 pending/debouncing/running 标为 superseded。"""
    keep = db.get(AnalysisJob, keep_job_id)
    if not keep:
        return 0
    n = 0
    from sqlalchemy import select

    rows = db.scalars(
        select(AnalysisJob).where(
            AnalysisJob.repo_full_name == repo_full_name,
            AnalysisJob.status.in_(("pending", "debouncing", "running", "awaiting_probe")),
        )
    ).all()
    for j in rows:
        if j.id == keep_job_id:
            continue
        if not _same_analysis_stream(keep, j):
            continue
        mark_cancelled(j)
        n += 1
    if n:
        db.commit()
    return n


def _cancel_superseded(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(AnalysisJob, job_id)
        if job and job.status in ("pending", "debouncing", "running", "awaiting_probe"):
            mark_cancelled(job)
            db.commit()
    finally:
        db.close()


def _fire(key: str, params: dict[str, Any]) -> None:
    with _lock:
        slot = _pending.pop(key, None)
    if not slot:
        return
    db = SessionLocal()
    try:
        job = db.get(AnalysisJob, slot.job_id)
        if not job or job.status in ("superseded", "cancelled"):
            return
        if job.head_sha != slot.head_sha:
            return
        job.status = "pending"
        db.commit()
    finally:
        db.close()

    # Webhook 响应已结束，background_tasks 无效，必须走独立线程
    schedule_analyze_merge(background_tasks=None, **params)


def register_debounced_analysis(
    *,
    db: Session,
    background_tasks: BackgroundTasks | None,
    job: AnalysisJob,
    clone_url: str,
) -> dict[str, Any]:
    settings = get_settings()
    window = max(0, int(settings.webhook_debounce_seconds))
    key = branch_key(job.repo_full_name, job.ref)
    supersede_branch_stale_jobs(db, repo_full_name=job.repo_full_name, ref=job.ref, keep_job_id=job.id)

    kwargs = dict(
        job_id=job.id,
        provider=job.provider,
        repo_full_name=job.repo_full_name,
        clone_url=clone_url,
        base_sha=job.base_sha,
        head_sha=job.head_sha,
        ref=job.ref,
    )

    if window <= 0:
        job.status = "pending"
        db.commit()
        meta = schedule_analyze_merge(background_tasks=background_tasks, **kwargs)
        return meta

    job.status = "debouncing"
    db.commit()

    with _lock:
        old = _pending.get(key)
        if old:
            old.timer.cancel()
            _cancel_superseded(old.job_id)

        def on_timer() -> None:
            _fire(key, kwargs)

        timer = threading.Timer(window, on_timer)
        _pending[key] = _Slot(job_id=job.id, head_sha=job.head_sha, timer=timer)
        timer.daemon = True
        timer.start()

    return {"runner": "debounced", "debounce_seconds": window, "task_id": None}