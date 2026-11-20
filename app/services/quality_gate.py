"""质量门禁：基于 AnalysisJob 真实字段 + 可选 CI 覆盖率回传。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db.models import AnalysisJob, Repository

REASON_LABELS: dict[str, str] = {
    "incremental_coverage_low": "增量覆盖率不足",
    "analysis_failed": "分析任务失败",
    "core_api_regression": "核心接口回归失败",
    "high_risk_unreviewed": "高危模块未评审",
    "pending_coverage": "待覆盖率回传",
}

HIGH_RISK_API_THRESHOLD = 5
HIGH_RISK_SYMBOL_THRESHOLD = 8


def _line_range_stats(job: AnalysisJob) -> tuple[int, int]:
    suspects = job.changed_symbols or {}
    line_ranges = suspects.get("line_ranges") or []
    files: set[str] = set()
    lines = 0
    for lr in line_ranges:
        if not isinstance(lr, dict):
            continue
        path = lr.get("path")
        if path:
            files.add(path)
        start = int(lr.get("start") or 0)
        end = int(lr.get("end") or start)
        lines += max(0, end - start + 1)
    return len(files), lines


def _api_count(job: AnalysisJob) -> int:
    apis = job.affected_apis or {}
    return int(apis.get("count") or 0)


def _symbol_count(job: AnalysisJob) -> int:
    suspects = job.changed_symbols or {}
    symbols = suspects.get("symbols") or []
    return len(symbols)


def build_gate_result(
    job: AnalysisJob,
    *,
    threshold: int,
    incremental_coverage_pct: float | None = None,
    tests_passed: bool | None = None,
    override_reason: str | None = None,
) -> dict[str, Any]:
    changed_files, changed_lines = _line_range_stats(job)
    api_count = _api_count(job)
    symbol_count = _symbol_count(job)
    now = datetime.utcnow().isoformat()

    base: dict[str, Any] = {
        "changed_files": changed_files,
        "changed_lines": changed_lines,
        "api_impact": api_count,
        "symbol_count": symbol_count,
        "coverage_threshold": threshold,
        "evaluated_at": now,
        "incremental_coverage_pct": incremental_coverage_pct,
        "coverage_source": "ci" if incremental_coverage_pct is not None else "pending",
        "tests_passed": tests_passed,
    }

    if job.status == "failed":
        return {
            **base,
            "gate": "BLOCK",
            "block_reason": "analysis_failed",
            "block_reason_label": REASON_LABELS["analysis_failed"],
        }

    if job.status not in ("completed", "running"):
        return {
            **base,
            "gate": "PENDING",
            "block_reason": None,
            "block_reason_label": None,
        }

    if override_reason:
        return {
            **base,
            "gate": "BLOCK",
            "block_reason": override_reason,
            "block_reason_label": REASON_LABELS.get(override_reason, override_reason),
        }

    if incremental_coverage_pct is None:
        return {
            **base,
            "gate": "PENDING",
            "block_reason": "pending_coverage",
            "block_reason_label": REASON_LABELS["pending_coverage"],
        }

    cov = float(incremental_coverage_pct)
    if tests_passed is False and api_count > 0:
        return {
            **base,
            "gate": "BLOCK",
            "block_reason": "core_api_regression",
            "block_reason_label": REASON_LABELS["core_api_regression"],
            "incremental_coverage_pct": cov,
            "coverage_source": "ci",
        }

    if cov < threshold:
        return {
            **base,
            "gate": "BLOCK",
            "block_reason": "incremental_coverage_low",
            "block_reason_label": REASON_LABELS["incremental_coverage_low"],
            "incremental_coverage_pct": cov,
            "coverage_source": "ci",
        }

    if api_count >= HIGH_RISK_API_THRESHOLD and symbol_count >= HIGH_RISK_SYMBOL_THRESHOLD:
        return {
            **base,
            "gate": "BLOCK",
            "block_reason": "high_risk_unreviewed",
            "block_reason_label": REASON_LABELS["high_risk_unreviewed"],
            "incremental_coverage_pct": cov,
            "coverage_source": "ci",
        }

    return {
        **base,
        "gate": "PASS",
        "block_reason": None,
        "block_reason_label": None,
        "incremental_coverage_pct": cov,
        "coverage_source": "ci",
    }


def threshold_for_repo(job: AnalysisJob, repo: Repository | None, default: int = 80) -> int:
    if repo and repo.full_name == job.repo_full_name:
        return repo.coverage_threshold
    return default


def apply_gate_result(
    job: AnalysisJob,
    repo: Repository | None,
    *,
    incremental_coverage_pct: float | None = None,
    tests_passed: bool | None = None,
) -> dict[str, Any]:
    threshold = threshold_for_repo(job, repo)
    prev = job.gate_result or {}
    cov = incremental_coverage_pct
    if cov is None and prev.get("incremental_coverage_pct") is not None:
        cov = float(prev["incremental_coverage_pct"])
    tests = tests_passed
    if tests is None and prev.get("tests_passed") is not None:
        tests = bool(prev["tests_passed"])

    result = build_gate_result(
        job,
        threshold=threshold,
        incremental_coverage_pct=cov,
        tests_passed=tests,
    )
    job.gate_result = result
    return result


def gate_snapshot_for_dashboard(job: AnalysisJob) -> dict[str, Any]:
    gr = job.gate_result or {}
    cov = gr.get("incremental_coverage_pct")
    return {
        "commit": (job.head_sha or "")[:8],
        "repo": job.repo_full_name,
        "changed_files": int(gr.get("changed_files") or 0),
        "api_impact": int(gr.get("api_impact") or _api_count(job)),
        "coverage": round(float(cov), 1) if cov is not None else None,
        "gate": gr.get("gate") or "PENDING",
        "time": job.created_at.isoformat() if job.created_at else None,
        "job_id": job.id,
        "block_reason_label": gr.get("block_reason_label"),
    }