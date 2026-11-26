from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
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


def _utc_dt(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _norm_repo_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _path_tail_segments(path: str, n: int = 4) -> str:
    parts = [seg for seg in _norm_repo_path(path).split("/") if seg]
    if not parts:
        return ""
    return "/".join(parts[-n:])


def _paths_match(stored: str, needle: str) -> bool:
    a = _norm_repo_path(stored)
    b = _norm_repo_path(needle)
    if not a or not b:
        return False
    if a == b:
        return True
    if a.endswith("/" + b) or b.endswith("/" + a):
        return True
    a_parts = [seg for seg in a.split("/") if seg]
    b_parts = [seg for seg in b.split("/") if seg]
    if a_parts and b_parts and a_parts[-1] != b_parts[-1]:
        return False
    if len(a_parts) <= len(b_parts) and b_parts[-len(a_parts) :] == a_parts:
        return True
    if len(b_parts) <= len(a_parts) and a_parts[-len(b_parts) :] == b_parts:
        return True
    return _path_tail_segments(a) == _path_tail_segments(b)


def _line_range_span(lr: dict) -> tuple[int | None, int | None]:
    start = lr.get("start") if lr.get("start") is not None else lr.get("start_line")
    end = lr.get("end") if lr.get("end") is not None else lr.get("end_line")
    if start is None:
        return None, None
    s = int(start)
    e = int(end if end is not None else start)
    return s, e


def _match_path_in_job(job: AnalysisJob, needle: str) -> dict | None:
    suspects = job.changed_symbols or {}
    for lr in suspects.get("line_ranges") or []:
        if not isinstance(lr, dict):
            continue
        raw = lr.get("path") or lr.get("file")
        if not raw or not _paths_match(str(raw), needle):
            continue
        start, end = _line_range_span(lr)
        out: dict = {
            "job_id": str(job.id),
            "repo": job.repo_full_name,
            "path": _norm_repo_path(str(raw)),
        }
        if start is not None:
            out["start_line"] = start
            out["end_line"] = end
        return out
    for sym in suspects.get("symbols") or []:
        if not isinstance(sym, dict):
            continue
        raw = sym.get("file")
        if not raw or not _paths_match(str(raw), needle):
            continue
        start = sym.get("start_line") or sym.get("start")
        end = sym.get("end_line") or sym.get("end") or start
        out = {
            "job_id": str(job.id),
            "repo": job.repo_full_name,
            "path": _norm_repo_path(str(raw)),
        }
        if start is not None:
            out["start_line"] = int(start)
            out["end_line"] = int(end if end is not None else start)
        return out
    return None


def _find_hotspot_job(
    db: Session,
    path: str,
    *,
    repo: str | None = None,
    days: int = 30,
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    scopes: list[str | None] = [repo] if repo else []
    if repo is not None:
        scopes.append(None)
    elif None not in scopes:
        scopes.append(None)
    for scope in scopes:
        stmt = (
            select(AnalysisJob)
            .where(AnalysisJob.created_at >= since)
            .order_by(AnalysisJob.created_at.desc())
        )
        if scope:
            stmt = stmt.where(AnalysisJob.repo_full_name == scope)
        for job in db.scalars(stmt):
            hit = _match_path_in_job(job, path)
            if hit:
                return hit
    raise HTTPException(status_code=404, detail="未找到包含该文件路径的分析任务")


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
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    for job in jobs:
        gr = job.gate_result or {}
        gate = str(gr.get("gate") or "").upper()
        line_ranges = (job.changed_symbols or {}).get("line_ranges") or []
        paths: list[str] = []
        range_by_path: dict[str, dict] = {}
        for lr in line_ranges:
            if isinstance(lr, dict) and lr.get("path"):
                p = _norm_repo_path(str(lr["path"]))
                paths.append(p)
                range_by_path[p] = lr
        if not paths:
            continue
        weight = 1.0
        if gate == "BLOCK":
            weight += 2.0
        job_ts = _utc_dt(job.created_at)
        for p in set(paths):
            norm = _norm_repo_path(p)
            bucket = scores.setdefault(
                norm,
                {
                    "path": norm,
                    "change_hits": 0,
                    "block_hits": 0,
                    "score": 0.0,
                    "latest_job_id": None,
                    "repo": None,
                    "_latest_at": epoch,
                },
            )
            bucket["change_hits"] += 1
            bucket["score"] += weight
            if gate == "BLOCK":
                bucket["block_hits"] += 1
            if bucket["latest_job_id"] is None or job_ts >= _utc_dt(bucket["_latest_at"]):
                bucket["_latest_at"] = job_ts
                bucket["latest_job_id"] = str(job.id)
                bucket["repo"] = job.repo_full_name
                lr = range_by_path.get(p) or range_by_path.get(norm)
                if lr:
                    start = lr.get("start") if lr.get("start") is not None else lr.get("start_line")
                    end = lr.get("end") if lr.get("end") is not None else lr.get("end_line")
                    if start is not None:
                        bucket["start_line"] = int(start)
                        bucket["end_line"] = int(end if end is not None else start)
    ranked = sorted(scores.values(), key=lambda x: x["score"], reverse=True)[:limit]
    for row in ranked:
        row["score"] = round(float(row["score"]), 1)
        row.pop("_latest_at", None)
    return ranked


def _case_compress_pct(jobs: list[AnalysisJob]) -> int:
    gated = [j for j in jobs if (j.gate_result or {}).get("gate") in ("PASS", "BLOCK")]
    if not gated:
        return 0
    apis = [int((j.gate_result or {}).get("api_impact") or 0) for j in gated]
    avg_api = sum(apis) / len(apis)
    ratio = max(0, min(95, round(100 - avg_api * 6)))
    return ratio


@router.get("/hotspot-resolve")
def resolve_hotspot_job(
    db: Session = Depends(get_db),
    path: str = Query(..., min_length=1),
    repo: str | None = Query(None, description="仓库 full_name，可选缩小范围"),
    days: int = Query(30, ge=1, le=90),
) -> dict:
    """按文件路径反查最近 N 天内包含该变更的分析任务，用于热点「查看代码」跳转。"""
    return _find_hotspot_job(db, path, repo=repo, days=days)


@router.get("/overview")
def dashboard_overview(
    db: Session = Depends(get_db),
    days: int = Query(7, ge=1, le=90),
    repo: str | None = Query(None, description="仓库 full_name，空=全部"),
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    hotspot_since = datetime.now(timezone.utc) - timedelta(days=30)
    stmt = (
        select(AnalysisJob)
        .where(AnalysisJob.created_at >= since)
        .order_by(AnalysisJob.created_at.desc())
    )
    if repo:
        stmt = stmt.where(AnalysisJob.repo_full_name == repo)
    jobs = list(db.scalars(stmt).all())

    hotspot_stmt = (
        select(AnalysisJob)
        .where(AnalysisJob.created_at >= hotspot_since)
        .order_by(AnalysisJob.created_at.desc())
    )
    if repo:
        hotspot_stmt = hotspot_stmt.where(AnalysisJob.repo_full_name == repo)
    hotspot_jobs = list(db.scalars(hotspot_stmt).all())

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
        "code_hotspots": _code_hotspots(hotspot_jobs, limit=5),
    }