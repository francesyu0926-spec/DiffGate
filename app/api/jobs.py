from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import GateReportIn
from app.db.models import AnalysisJob, Repository
from app.db.session import get_db
from app.config import get_settings
from app.graph.stores import load_job_graph
from app.services.code_snippet import job_code_view
from app.services.quality_gate import apply_gate_result
from app.utils.time_format import as_utc_iso

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _ref_branch(ref: str) -> str:
    return ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref


def _trigger_label(provider: str) -> str:
    if provider == "local":
        return "手动触发"
    if provider == "github":
        return "GitHub Webhook"
    if provider == "gitlab":
        return "GitLab Webhook"
    return provider


def _job_list_item(job: AnalysisJob) -> dict:
    gr = job.gate_result or {}
    suspects = job.changed_symbols or {}
    symbols = suspects.get("symbols") or []
    line_ranges = suspects.get("line_ranges") or []
    changed_files = int(
        gr.get("changed_files")
        or len({lr["path"] for lr in line_ranges if isinstance(lr, dict) and lr.get("path")})
    )
    method_count = int(gr.get("symbol_count") or len(symbols))
    api_count = int((job.affected_apis or {}).get("count", 0) or gr.get("api_impact") or 0)
    commit_message = (suspects.get("head_commit_message") or "").strip()
    return {
        "id": job.id,
        "provider": job.provider,
        "repo": job.repo_full_name,
        "ref": job.ref,
        "ref_branch": _ref_branch(job.ref),
        "status": job.status,
        "base_sha": job.base_sha[:8],
        "head_sha": job.head_sha[:8],
        "api_count": api_count,
        "changed_files": changed_files,
        "method_count": method_count,
        "trigger_label": _trigger_label(job.provider),
        "commit_message": commit_message or None,
        "created_at": as_utc_iso(job.created_at),
    }


@router.get("/stats/overview")
def jobs_stats_overview(db: Session = Depends(get_db)) -> dict:
    jobs = list(db.scalars(select(AnalysisJob)).all())
    repos = list(db.scalars(select(Repository)).all())
    total = len(jobs)
    durations: list[float] = []
    api_counts: list[int] = []
    dispatched = 0
    completed = 0
    for job in jobs:
        if job.status != "completed":
            continue
        completed += 1
        apis = (job.affected_apis or {}).get("count", 0) or 0
        api_counts.append(int(apis))
        if apis > 0:
            dispatched += 1
        if job.created_at and job.updated_at:
            durations.append((job.updated_at - job.created_at).total_seconds())

    avg_seconds = round(sum(durations) / len(durations), 1) if durations else 0.0
    avg_impacted = round(sum(api_counts) / len(api_counts), 1) if api_counts else 0.0
    baseline_apis = (
        round(sum(r.ast_api_count for r in repos) / len(repos)) if repos else 0
    )
    if baseline_apis <= 0 and repos:
        baseline_apis = max((r.ast_api_count for r in repos), default=0)
    convergence = 0.0
    if api_counts and baseline_apis > 0:
        convergence = round((1 - avg_impacted / baseline_apis) * 100, 1)
        convergence = min(99.9, max(0.0, convergence))
    trigger_pct = round(dispatched / completed * 100, 1) if completed else 0.0
    ever_hit_api = any(
        int((j.affected_apis or {}).get("count") or 0) > 0
        for j in jobs
        if j.status == "completed"
    )

    return {
        "total": total,
        "avg_seconds": avg_seconds,
        "avg_baseline_apis": int(baseline_apis),
        "avg_impacted_apis": avg_impacted,
        "api_convergence_pct": convergence,
        "regression_trigger_pct": trigger_pct,
        "ever_hit_api": ever_hit_api,
    }


@router.get("")
def list_jobs(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: str | None = Query(None, description="仓库 full_name"),
    status: str | None = Query(None, description="pending|running|completed|failed"),
) -> dict:
    stmt = select(AnalysisJob).order_by(AnalysisJob.created_at.desc())
    if repo:
        stmt = stmt.where(AnalysisJob.repo_full_name == repo)
    if status:
        stmt = stmt.where(AnalysisJob.status == status)
    stmt = stmt.offset(offset).limit(limit)
    rows = db.scalars(stmt).all()
    return {
        "items": [_job_list_item(j) for j in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get("/{job_id}/graph")
def get_job_graph(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    graph = load_job_graph(job_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not available for this job")
    return graph


@router.get("/{job_id}/code-diff")
def get_job_code_diff(
    job_id: str,
    db: Session = Depends(get_db),
    file: str = Query(..., min_length=1),
    start_line: int = Query(..., ge=1),
    end_line: int = Query(..., ge=1),
    node_type: str = Query("symbol", pattern="^(api|changed|symbol)$"),
    highlight: str | None = Query(None, description="Comma-separated qualified names for call-site highlight"),
) -> dict:
    job = db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if end_line < start_line:
        raise HTTPException(status_code=400, detail="end_line 必须 >= start_line")
    settings = get_settings()
    hints = [h.strip() for h in (highlight or "").split(",") if h.strip()]
    repo_rec = db.scalar(select(Repository).where(Repository.full_name == job.repo_full_name))
    scan_root = (repo_rec.scan_root if repo_rec and repo_rec.scan_root else ".") or "."
    try:
        return job_code_view(
            repo_full_name=job.repo_full_name,
            clone_root=settings.repo_clone_root,
            base_sha=job.base_sha,
            head_sha=job.head_sha,
            file_path=file,
            start_line=start_line,
            end_line=end_line,
            node_type=node_type,
            highlight_qnames=hints or None,
            scan_root=scan_root,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取代码失败: {exc}") from exc


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "provider": job.provider,
        "repo": job.repo_full_name,
        "ref": job.ref,
        "base_sha": job.base_sha,
        "head_sha": job.head_sha,
        "status": job.status,
        "affected_apis": job.affected_apis,
        "changed_symbols": job.changed_symbols,
        "error_message": job.error_message,
        "gate_result": job.gate_result,
        "created_at": as_utc_iso(job.created_at),
    }


@router.post("/{job_id}/gate-report")
def report_job_gate(job_id: str, body: GateReportIn, db: Session = Depends(get_db)) -> dict:
    """CI / 精准回归调度中心回传覆盖率与用例结果。"""
    job = db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    repo = db.scalar(select(Repository).where(Repository.full_name == job.repo_full_name))
    probes = (
        [p.model_dump() for p in body.coverage_probes] if body.coverage_probes is not None else None
    )
    gate = apply_gate_result(
        job,
        repo,
        incremental_coverage_pct=body.incremental_coverage_pct,
        tests_passed=body.tests_passed,
        coverage_probes=probes,
    )
    db.commit()
    return {"ok": True, "job_id": job_id, "gate_result": gate}