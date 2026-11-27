"""分析任务执行状态机（Push/MR → 分析 → 探针 → 门禁）。"""

from __future__ import annotations

from typing import Any

from app.db.models import AnalysisJob

# 与产品状态图对齐（debouncing 为内部防抖，对外展示为 pending）
PROBE_UI_HINTS: dict[str, str] = {
    "awaiting_probe": "等待测试环境回传 gate-report；请确认调度中心或 CI 探针已启用。",
    "timeout": "探针回传超时：请检查测试环境连通性，可点击下方「手动重跑回归采集」唤醒收集。",
    "env_mismatch": "测试环境代码版本落后，请重新部署后再回传 gate-report。",
}

EXECUTION_LABELS: dict[str, str] = {
    "pending": "排队等待分析",
    "debouncing": "排队等待分析",
    "running": "执行 Diff / AST 溯源",
    "cancelled": "已由新提交取代",
    "superseded": "已由新提交取代",
    "failed": "分析执行异常",
    "awaiting_probe": "等待探针回传报告",
    "timeout": "探针回传超时",
    "env_mismatch": "运行环境版本错位",
    "completed": "分析与数据收集完成",
}

_ANALYSIS_VIEW_STATUSES = frozenset(
    {"completed", "awaiting_probe", "timeout", "env_mismatch", "running"}
)


def execution_label(status: str | None) -> str:
    return EXECUTION_LABELS.get(str(status or ""), str(status or "unknown"))


def is_cancelled_status(status: str | None) -> bool:
    return str(status or "") in ("cancelled", "superseded")


def analysis_result_visible(status: str | None) -> bool:
    """Diff/拓扑是否可供展示（分析阶段已结束）。"""
    s = str(status or "")
    return s in _ANALYSIS_VIEW_STATUSES or s == "failed"


def _meta(job: AnalysisJob) -> dict[str, Any]:
    raw = job.job_metadata
    return dict(raw) if isinstance(raw, dict) else {}


def touch_execution_phase(job: AnalysisJob, *, note: str | None = None) -> None:
    meta = _meta(job)
    meta["execution_phase"] = job.status
    meta["execution_phase_label"] = execution_label(job.status)
    if note:
        meta["execution_note"] = note
    job.job_metadata = meta


def mark_cancelled(job: AnalysisJob, reason: str | None = None) -> None:
    job.status = "cancelled"
    job.error_message = reason or "被同分支或 MR 更新的提交取代"
    touch_execution_phase(job, note=reason)


def finalize_after_analysis(job: AnalysisJob) -> None:
    """
    分析 runner 写完 gate_result 后：
    - 零有效行 / 无需覆盖率 → completed（直达门禁）
    - 否则 → awaiting_probe
    """
    if is_cancelled_status(job.status):
        return
    gr = job.gate_result or {}
    if gr.get("coverage_not_required"):
        job.status = "completed"
        touch_execution_phase(job)
        return
    exec_lines = int(gr.get("executable_changed_lines") or gr.get("changed_lines") or 0)
    if exec_lines <= 0 and int(gr.get("diff_lines_total") or 0) > 0:
        job.status = "completed"
        touch_execution_phase(job)
        return
    if gr.get("incremental_coverage_pct") is not None and gr.get("coverage_probes"):
        job.status = "completed"
        touch_execution_phase(job)
        return
    job.status = "awaiting_probe"
    touch_execution_phase(job)


def mark_awaiting_probe(job: AnalysisJob) -> None:
    if is_cancelled_status(job.status):
        return
    job.status = "awaiting_probe"
    touch_execution_phase(job)


def mark_probe_timeout(job: AnalysisJob) -> None:
    if is_cancelled_status(job.status):
        return
    job.status = "timeout"
    gr = dict(job.gate_result or {})
    gr["probe_ui_hint"] = PROBE_UI_HINTS["timeout"]
    job.gate_result = gr
    touch_execution_phase(job, note="超过配置时间未收到 gate-report")


def mark_env_mismatch(job: AnalysisJob, *, running: str, target: str) -> None:
    if is_cancelled_status(job.status):
        return
    job.status = "env_mismatch"
    gr = dict(job.gate_result or {})
    gr["probe_status"] = "ENV_MISMATCH"
    gr["block_reason"] = "runtime_commit_mismatch"
    from app.services.quality_gate import REASON_LABELS

    gr["block_reason_label"] = REASON_LABELS.get(
        "runtime_commit_mismatch", "运行环境版本错位"
    )
    gr["probe_ui_hint"] = PROBE_UI_HINTS["env_mismatch"]
    gr["running_commit_sha"] = running
    gr["target_commit_sha"] = target
    job.gate_result = gr
    touch_execution_phase(
        job,
        note=f"Running {running[:8]} ≠ Target {target[:8]}",
    )


def mark_completed_after_probe(job: AnalysisJob) -> None:
    if is_cancelled_status(job.status):
        return
    job.status = "completed"
    gr = dict(job.gate_result or {})
    gr.pop("probe_status", None)
    job.gate_result = gr
    touch_execution_phase(job)


def normalize_legacy_superseded(job: AnalysisJob) -> None:
    if job.status == "superseded":
        job.status = "cancelled"
        touch_execution_phase(job)