"""探针长时间未回传 → TIMEOUT 熔断。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db.models import AnalysisJob
from app.db.session import SessionLocal
from app.services.job_execution_state import PROBE_UI_HINTS, mark_probe_timeout
from app.services.quality_gate import REASON_LABELS


def _naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def fuse_stale_probe_returns(*, limit: int = 200) -> int:
    """
    已完成分析但迟迟未收到 gate-report 的任务标记为 probe TIMEOUT。
    默认窗口见 settings.probe_return_timeout_minutes。
    """
    settings = get_settings()
    window = max(5, int(settings.probe_return_timeout_minutes))
    cutoff = datetime.utcnow() - timedelta(minutes=window)
    db = SessionLocal()
    n = 0
    try:
        rows = db.scalars(
            select(AnalysisJob)
            .where(AnalysisJob.status.in_(("completed", "awaiting_probe")))
            .order_by(AnalysisJob.updated_at.asc())
            .limit(limit)
        ).all()
        for job in rows:
            gr = dict(job.gate_result or {})
            if gr.get("probe_status") == "TIMEOUT":
                continue
            src = gr.get("coverage_source")
            if src not in (None, "pending", "ci") and gr.get("incremental_coverage_pct") is not None:
                continue
            if gr.get("incremental_coverage_pct") is not None and src == "ci":
                continue
            if gr.get("gate") not in (None, "PENDING") and gr.get("incremental_coverage_pct") is not None:
                continue
            ts = _naive_utc(job.updated_at or job.created_at)
            if ts and ts > cutoff:
                continue
            if gr.get("coverage_probes"):
                continue
            gr["probe_status"] = "TIMEOUT"
            gr["coverage_source"] = "probe_timeout"
            gr["block_reason"] = "probe_return_timeout"
            gr["block_reason_label"] = REASON_LABELS.get(
                "probe_return_timeout", "探针回传超时"
            )
            gr["probe_timeout_hint"] = (
                f"超过 {window} 分钟未收到有效 gate-report；请检查测试环境连通性、"
                "调度中心与 coverage combine/flush 是否正常。"
            )
            gr["probe_ui_hint"] = PROBE_UI_HINTS["timeout"]
            gr["gate"] = gr.get("gate") or "PENDING"
            job.gate_result = gr
            mark_probe_timeout(job)
            n += 1
        if n:
            db.commit()
    finally:
        db.close()
    return n