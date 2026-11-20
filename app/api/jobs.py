from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import GateReportIn
from app.db.models import AnalysisJob, Repository
from app.db.session import get_db
from app.graph.stores import load_job_graph
from app.services.quality_gate import apply_gate_result

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    stmt = select(AnalysisJob).order_by(AnalysisJob.created_at.desc()).offset(offset).limit(limit)
    rows = db.scalars(stmt).all()
    return {
        "items": [
            {
                "id": j.id,
                "provider": j.provider,
                "repo": j.repo_full_name,
                "ref": j.ref,
                "status": j.status,
                "base_sha": j.base_sha[:8],
                "head_sha": j.head_sha[:8],
                "api_count": (j.affected_apis or {}).get("count", 0) if j.affected_apis else 0,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in rows
        ],
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
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


@router.post("/{job_id}/gate-report")
def report_job_gate(job_id: str, body: GateReportIn, db: Session = Depends(get_db)) -> dict:
    """CI / 精准回归调度中心回传覆盖率与用例结果。"""
    job = db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    repo = db.scalar(select(Repository).where(Repository.full_name == job.repo_full_name))
    gate = apply_gate_result(
        job,
        repo,
        incremental_coverage_pct=body.incremental_coverage_pct,
        tests_passed=body.tests_passed,
    )
    db.commit()
    return {"ok": True, "job_id": job_id, "gate_result": gate}