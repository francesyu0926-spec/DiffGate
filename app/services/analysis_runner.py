"""分析任务执行：供 BackgroundTasks 或 Celery 共用。"""

from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks
from git import Repo
from sqlalchemy import select

from app.config import get_settings
from app.db.models import AnalysisJob, Repository
from app.db.session import SessionLocal
from app.services.dispatch import notify_dispatch_center
from app.services.git_clone import (
    clear_clone_dest,
    clone_or_fallback,
    git_ssh_command_for_repo,
    git_ssh_process_env,
)
from app.services.impact import analyze_impact
from app.services.quality_gate import apply_gate_result


def run_analyze_merge(
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
        repo_dir = (Path(settings.repo_clone_root) / safe_name).resolve()
        clear_clone_dest(repo_dir)

        repo_rec = db.scalar(select(Repository).where(Repository.full_name == repo_full_name))
        clone_or_fallback(repo_rec, clone_url, repo_dir, provider, no_checkout=True)
        scan_root = (repo_rec.scan_root if repo_rec and repo_rec.scan_root else ".") or "."

        repo = Repo(str(repo_dir))

        def _fetch_and_checkout() -> None:
            repo.git.fetch("origin", base_sha, depth=50)
            repo.git.fetch("origin", head_sha, depth=50)
            repo.git.checkout(head_sha)

        with git_ssh_command_for_repo(repo_rec) as ssh_cmd:
            with git_ssh_process_env(ssh_cmd):
                if ssh_cmd:
                    with repo.git.custom_environment(GIT_SSH_COMMAND=ssh_cmd):
                        _fetch_and_checkout()
                else:
                    _fetch_and_checkout()

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

        head_commit_message = ""
        try:
            head_commit_message = (repo.commit(head_sha).message or "").strip().split("\n")[0][:160]
        except Exception:
            pass

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
                "diff_summary": payload.get("diff_summary"),
                "head_commit_message": head_commit_message,
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


def schedule_analyze_merge(
    *,
    background_tasks: BackgroundTasks | None,
    job_id: str,
    provider: str,
    repo_full_name: str,
    clone_url: str,
    base_sha: str,
    head_sha: str,
    ref: str,
) -> dict:
    """默认走 BackgroundTasks，无需 Redis/Celery Worker。"""
    settings = get_settings()
    kwargs = dict(
        job_id=job_id,
        provider=provider,
        repo_full_name=repo_full_name,
        clone_url=clone_url,
        base_sha=base_sha,
        head_sha=head_sha,
        ref=ref,
    )
    if settings.use_background_tasks:
        if background_tasks is None:
            run_analyze_merge(**kwargs)
            return {"runner": "inline", "task_id": None}
        background_tasks.add_task(run_analyze_merge, **kwargs)
        return {"runner": "background", "task_id": None}

    from app.tasks.analysis import analyze_merge_task

    task = analyze_merge_task.delay(**kwargs)
    return {"runner": "celery", "task_id": task.id}