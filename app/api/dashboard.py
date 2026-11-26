from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AnalysisJob, Repository
from app.db.session import get_db
from app.services.quality_gate import (
    REASON_LABELS,
    gate_snapshot_for_dashboard,
    reconcile_gates_for_jobs,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _repo_threshold_map(db: Session) -> dict[str, int]:
    repos = db.scalars(select(Repository)).all()
    return {r.full_name: r.coverage_threshold for r in repos}


def _default_threshold(repo_map: dict[str, int], repo: str | None) -> int:
    if repo and repo in repo_map:
        return repo_map[repo]
    if repo_map:
        return round(sum(repo_map.values()) / len(repo_map))
    return 80


def _bucket_trend(jobs: list[AnalysisJob], days: int, threshold: int) -> dict:
    start = datetime.utcnow().date() - timedelta(days=days - 1)
    labels: list[str] = []
    lines_by_day: list[int] = []
    cov_by_day: list[float | None] = []
    day_keys: list[datetime.date] = []
    for i in range(days):
        d = start + timedelta(days=i)
        day_keys.append(d)
        labels.append(d.strftime("%m-%d"))

    buckets: dict[datetime.date, dict] = defaultdict(lambda: {"lines": 0, "coverages": []})
    for job in jobs:
        if not job.created_at:
            continue
        d = job.created_at.date()
        if d < start or d > day_keys[-1]:
            continue
        gr = job.gate_result or {}
        buckets[d]["lines"] += int(gr.get("changed_lines") or 0)
        cov = gr.get("incremental_coverage_pct")
        if cov is not None:
            buckets[d]["coverages"].append(float(cov))

    for d in day_keys:
        b = buckets[d]
        lines_by_day.append(b["lines"])
        cov_by_day.append(
            round(sum(b["coverages"]) / len(b["coverages"]), 1) if b["coverages"] else None
        )

    return {
        "labels": labels,
        "changed_lines": lines_by_day,
        "coverage": cov_by_day,
        "threshold": threshold,
    }


def _intercept_reasons(blocked_jobs: list[AnalysisJob]) -> list[dict]:
    counts: dict[str, int] = defaultdict(int)
    for job in blocked_jobs:
        gr = job.gate_result or {}
        code = gr.get("block_reason")
        if not code or code == "pending_coverage":
            label = gr.get("block_reason_label") or REASON_LABELS.get("analysis_failed", "其他")
        else:
            label = REASON_LABELS.get(code, gr.get("block_reason_label") or code)
        counts[label] += 1
    if not counts:
        return []
    return [{"name": name, "value": value} for name, value in sorted(counts.items(), key=lambda x: -x[1])]


def _coverage_delta(jobs: list[AnalysisJob]) -> float:
    coverages: list[tuple[datetime, float]] = []
    for job in jobs:
        gr = job.gate_result or {}
        cov = gr.get("incremental_coverage_pct")
        if cov is not None and job.created_at:
            coverages.append((job.created_at, float(cov)))
    if len(coverages) < 2:
        return 0.0
    coverages.sort(key=lambda x: x[0])
    mid = len(coverages) // 2
    first = [c for _, c in coverages[:mid]]
    second = [c for _, c in coverages[mid:]]
    if not first or not second:
        return 0.0
    return round(sum(second) / len(second) - sum(first) / len(first), 1)


def _saved_hours(jobs: list[AnalysisJob]) -> int:
    total = 0.0
    for job in jobs:
        gr = job.gate_result or {}
        apis = int(gr.get("api_impact") or 0)
        if apis <= 0:
            continue
        total += max(0.5, apis * 1.2)
    return int(round(total))


def _repo_gate_stats(jobs: list[AnalysisJob]) -> list[dict]:
    by_repo: dict[str, dict[str, int]] = defaultdict(lambda: {"block_count": 0, "pending_count": 0})
    for job in jobs:
        repo = job.repo_full_name
        gr = job.gate_result or {}
        gate = gr.get("gate") or "PENDING"
        if gate == "BLOCK":
            by_repo[repo]["block_count"] += 1
        elif gate == "PENDING":
            by_repo[repo]["pending_count"] += 1
    return [
        {"full_name": name, **counts}
        for name, counts in sorted(by_repo.items(), key=lambda x: x[0].lower())
    ]


def _code_hotspots(jobs: list[AnalysisJob], limit: int = 5) -> list[dict]:
    """30 天内高频变更 / 门禁拦截文件的 Top N（规格：代码热点图）。"""
    scores: dict[str, dict] = {}
    for job in jobs:
        gr = job.gate_result or {}
        gate = str(gr.get("gate") or "").upper()
        paths = []
        for lr in (job.changed_symbols or {}).get("line_ranges") or []:
            if isinstance(lr, dict) and lr.get("path"):
                paths.append(str(lr["path"]))
        if not paths:
            continue
        weight = 1.0
        if gate == "BLOCK":
            weight += 2.0
        for p in set(paths):
            norm = p.replace("\\", "/")
            bucket = scores.setdefault(norm, {"path": norm, "change_hits": 0, "block_hits": 0, "score": 0.0})
            bucket["change_hits"] += 1
            bucket["score"] += weight
            if gate == "BLOCK":
                bucket["block_hits"] += 1
    ranked = sorted(scores.values(), key=lambda x: x["score"], reverse=True)[:limit]
    for row in ranked:
        row["score"] = round(float(row["score"]), 1)
    return ranked


def _case_compress_pct(jobs: list[AnalysisJob]) -> int:
    gated = [j for j in jobs if (j.gate_result or {}).get("gate") in ("PASS", "BLOCK")]
    if not gated:
        return 0
    apis = [int((j.gate_result or {}).get("api_impact") or 0) for j in gated]
    avg_api = sum(apis) / len(apis)
    ratio = max(0, min(95, round(100 - avg_api * 6)))
    return ratio


@router.get("/overview")
def dashboard_overview(
    db: Session = Depends(get_db),
    days: int = Query(7, ge=1, le=90),
    repo: str | None = Query(None, description="仓库 full_name，空=全部"),
) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    hotspot_since = datetime.utcnow() - timedelta(days=30)
    if repo:
        stmt = stmt.where(AnalysisJob.repo_full_name == repo)
    jobs = list(db.scalars(stmt).all())

    repos = db.scalars(select(Repository)).all()
    repo_map = _repo_threshold_map(db)
    default_threshold = _default_threshold(repo_map, repo)

    reconcile_gates_for_jobs(jobs, db)

    passed = 0
    blocked = 0
    pending = 0
    coverages: list[float] = []
    blocked_jobs: list[AnalysisJob] = []
    flows: list[dict] = []

    for job in jobs:
        gr = job.gate_result or {}
        gate = gr.get("gate") or "PENDING"
        if gate in ("PASS", "OVERRIDDEN"):
            passed += 1
        elif gate == "BLOCK":
            blocked += 1
            blocked_jobs.append(job)
        else:
            pending += 1

        cov = gr.get("incremental_coverage_pct")
        if cov is not None:
            coverages.append(float(cov))

        if len(flows) < 8:
            flows.append(gate_snapshot_for_dashboard(job))

    total_gates = passed + blocked
    first_pass_rate = round(passed / total_gates * 100, 1) if total_gates else 0.0
    avg_coverage = round(sum(coverages) / len(coverages), 1) if coverages else 0.0

    kpi = {
        "avg_coverage": avg_coverage,
        "coverage_sample_count": len(coverages),
        "coverage_delta": _coverage_delta(jobs),
        "gate_baseline": default_threshold,
        "first_pass_rate": first_pass_rate,
        "pass_count": passed,
        "block_count": blocked,
        "pending_count": pending,
        "high_risk_total": blocked,
        "saved_hours": _saved_hours(jobs),
        "case_compress_pct": _case_compress_pct(jobs),
    }

    trend = _bucket_trend(jobs, days, default_threshold)
    reasons = _intercept_reasons(blocked_jobs)
    repo_gate_stats = _repo_gate_stats(jobs)

    repo_total = db.scalar(select(func.count()).select_from(Repository)) or 0
    indexed_repo_count = (
        db.scalar(
            select(func.count())
            .select_from(Repository)
            .where(Repository.last_indexed_at.isnot(None), Repository.enabled.is_(True))
        )
        or 0
    )
    analysis_total = db.scalar(select(func.count()).select_from(AnalysisJob)) or 0
    if repo_total == 0:
        suggested_action = "add_repo"
    elif indexed_repo_count == 0:
        suggested_action = "index_repo"
    elif analysis_total == 0:
        suggested_action = "run_analysis"
    else:
        suggested_action = "ok"

    return {
        "filters": {
            "days": days,
            "repo": repo,
            "repos": [{"full_name": r.full_name, "id": r.id} for r in repos],
        },
        "home": {
            "repo_count": repo_total,
            "indexed_repo_count": indexed_repo_count,
            "jobs_in_range": len(jobs),
            "analysis_total": analysis_total,
            "suggested_action": suggested_action,
        },
        "kpi": kpi,
        "trend": trend,
        "intercept_reasons": reasons,
        "repo_gate_stats": repo_gate_stats,
        "recent_flows": flows,
    }