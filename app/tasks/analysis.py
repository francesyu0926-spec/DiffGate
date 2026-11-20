import shutil
import uuid
from pathlib import Path

from git import Repo
from sqlalchemy import select

from app.celery_app import celery
from app.config import get_settings
from app.db.models import AnalysisJob, Repository
from app.db.session import SessionLocal
from app.services.git_clone import clone_or_fallback
from app.services.dispatch import notify_dispatch_center
from app.services.impact import analyze_impact
from app.services.quality_gate import apply_gate_result


@celery.task(bind=True, name="diffgate.analyze_merge")
def analyze_merge_task(
    self,
    job_id: str,
    provider: str,
    repo_full_name: str,
    clone_url: str,
    base_sha: str,
    head_sha: str,
    ref: str,
) -> dict:
    settings = get_settings()
    db = SessionLocal()
    job: AnalysisJob | None = None
    try:
        job = db.get(AnalysisJob, job_id)
        if job:
            job.status = "running"
            db.commit()

        safe_name = repo_full_name.replace("/", "_")
        repo_dir = Path(settings.repo_clone_root) / safe_name
        repo_dir.parent.mkdir(parents=True, exist_ok=True)

        if repo_dir.exists():
            shutil.rmtree(repo_dir, ignore_errors=True)

        repo_rec = db.scalar(select(Repository).where(Repository.full_name == repo_full_name))
        clone_or_fallback(repo_rec, clone_url, repo_dir, provider, no_checkout=True)
        scan_root = (repo_rec.scan_root if repo_rec and repo_rec.scan_root else ".") or "."

        repo = Repo(str(repo_dir))
        repo.git.fetch("origin", base_sha, depth=50)
        repo.git.fetch("origin", head_sha, depth=50)
        repo.git.checkout(head_sha)

        report = analyze_impact(
            repo_path=repo_dir,
            base_sha=base_sha,
            head_sha=head_sha,
            repo_key=repo_full_name,
            use_neo4j=settings.use_neo4j,
            job_id=job_id,
            scan_root=scan_root,
        )

        test_suite = repo_rec.test_suite_id if repo_rec else None
        notify_dispatch_center(job_id, repo_full_name, ref, report, test_suite_id=test_suite)

        payload = report.to_dict()
        if job:
            job.status = "completed"
            job.affected_apis = {
                "apis": report.affected_apis,
                "count": len(report.affected_apis),
                "call_paths": report.call_paths,
            }
            job.changed_symbols = {
                "symbols": [s.qualified_name for s in report.suspect_functions],
                "suspects": payload["suspect_functions"],
                "line_ranges": payload["line_ranges"],
            }
            apply_gate_result(job, repo_rec)
            db.commit()

        return {"job_id": job_id, **payload}
    except Exception as exc:
        if job:
            job.status = "failed"
            job.error_message = str(exc)
            repo_rec = db.scalar(select(Repository).where(Repository.full_name == job.repo_full_name))
            apply_gate_result(job, repo_rec)
            db.commit()
        raise
    finally:
        db.close()