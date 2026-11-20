from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnalysisJob, Repository
from app.db.session import get_db
from app.services.quality_gate import (
    REASON_LABELS,
    apply_gate_result,
    gate_snapshot_for_dashboard,
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


def _ensure_gate_results(jobs: list[AnalysisJob], repo_map: dict[str, int], db: Session) -> None:
    dirty = False
    for job in jobs:
        if job.gate_result is not None:
            continue
        repo = db.scalar(select(Repository).where(Repository.full_name == job.repo_full_name))
        prev_cov = None
        apply_gate_result(job, repo, incremental_coverage_pct=prev_cov)
        dirty = True
    if dirty:
        db.commit()


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

    filled_coverage: list[float] = []
    last: float | None = None
    for c in cov_by_day:
        if c is not None:
            last = c
            filled_coverage.append(c)
        elif last is not None:
            filled_coverage.append(last)
        else:
            filled_coverage.append(float(threshold))

    return {
        "labels": labels,
        "changed_lines": lines_by_day,
        "coverage": filled_coverage,
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
    stmt = select(AnalysisJob).where(AnalysisJob.created_at >= since).order_by(AnalysisJob.created_at.desc())
    if repo:
        stmt = stmt.where(AnalysisJob.repo_full_name == repo)
    jobs = list(db.scalars(stmt).all())

    repos = db.scalars(select(Repository)).all()
    repo_map = _repo_threshold_map(db)
    default_threshold = _default_threshold(repo_map, repo)

    _ensure_gate_results(jobs, repo_map, db)

    passed = 0
    blocked = 0
    pending = 0
    coverages: list[float] = []
    blocked_jobs: list[AnalysisJob] = []
    flows: list[dict] = []

    for job in jobs:
        gr = job.gate_result or {}
        gate = gr.get("gate") or "PENDING"
        if gate == "PASS":
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

    return {
        "filters": {
            "days": days,
            "repo": repo,
            "repos": [{"full_name": r.full_name, "id": r.id} for r in repos],
        },
        "kpi": kpi,
        "trend": trend,
        "intercept_reasons": reasons,
        "recent_flows": flows,
        "demo_mode": False,
    }