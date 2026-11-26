"""分析任务执行：供 BackgroundTasks 或 Celery 共用。"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import BackgroundTasks
from git import Repo
from sqlalchemy import select

from app.config import get_settings
from app.db.models import AnalysisJob, Repository
from app.db.session import SessionLocal
from app.services.dispatch import notify_dispatch_center
from app.services.git_clone import (
    clone_or_fallback,
    git_ssh_command_for_repo,
    git_ssh_process_env,
)
from app.services.git_worktree import (
    ensure_commit_in_repo,
    is_worktree_path_only_error,
    prepare_job_worktree,
    remove_job_worktree,
)
from app.services.platform_notify import notify_platform
from app.parsers.frontend_trace import build_fullstack_impact
from app.services.cross_repo_trace import find_cross_repo_consumers
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
            if job.status in ("superseded", "debouncing"):
                return {"job_id": job_id, "skipped": job.status}
            job.status = "running"
            db.commit()

        safe_name = repo_full_name.replace("/", "_")
        repo_dir = (Path(settings.repo_clone_root) / safe_name).resolve()
        if not (repo_dir / ".git").is_dir():
            repo_dir.parent.mkdir(parents=True, exist_ok=True)

        repo_rec = db.scalar(select(Repository).where(Repository.full_name == repo_full_name))
        if not (repo_dir / ".git").is_dir():
            clone_or_fallback(repo_rec, clone_url, repo_dir, provider, no_checkout=True)
        scan_root = (repo_rec.scan_root if repo_rec and repo_rec.scan_root else ".") or "."

        repo = Repo(str(repo_dir))

        def _ensure_shas() -> None:
            ensure_commit_in_repo(repo, base_sha)
            ensure_commit_in_repo(repo, head_sha)

        with git_ssh_command_for_repo(repo_rec) as ssh_cmd:
            with git_ssh_process_env(ssh_cmd):
                if ssh_cmd:
                    with repo.git.custom_environment(GIT_SSH_COMMAND=ssh_cmd):
                        _ensure_shas()
                else:
                    _ensure_shas()

        analyze_path = repo_dir
        if settings.use_job_worktree:
            analyze_path = prepare_job_worktree(repo_dir, job_id, head_sha)
        else:
            repo.git.checkout(head_sha)

        fullstack: dict | None = None
        cross_repo: dict | None = None
        try:
            report = analyze_impact(
                repo_path=analyze_path,
                base_sha=base_sha,
                head_sha=head_sha,
                repo_key=repo_full_name,
                use_neo4j=settings.use_neo4j,
                job_id=job_id,
                scan_root=scan_root,
            )
            payload = report.to_dict()
            if settings.use_fullstack_trace:
                changed_paths = {lr.get("path") for lr in payload.get("line_ranges") or [] if lr.get("path")}
                try:
                    scan_roots: tuple[str, ...] = ("frontend", "web", "src", ".")
                    # analyze_path 即本次沙箱：主克隆或 data/worktrees/<job_id>/...
                    fullstack = build_fullstack_impact(
                        analyze_path,
                        changed_paths,
                        scan_roots=scan_roots,
                        backend_apis=report.affected_apis,
                    )
                    from app.graph.viz import augment_graph_with_frontend
                    from app.graph.stores import cache_job_graph, load_job_graph

                    base_graph = load_job_graph(job_id) or {}
                    if base_graph.get("nodes"):
                        augmented = augment_graph_with_frontend(base_graph, fullstack, report.affected_apis)
                        cache_job_graph(job_id, augmented)

                    api_paths = [str(a.get("path") or "") for a in report.affected_apis]
                    fe_paths = [str(c.get("path") or "") for c in (fullstack.get("frontend_api_calls") or [])]
                    cross_repo = find_cross_repo_consumers(
                        db,
                        provider_repo=repo_full_name,
                        provider_api_paths=api_paths,
                        extra_paths=fe_paths,
                    )
                except Exception:
                    fullstack = fullstack or {"error": "fullstack_trace_failed"}
                    cross_repo = cross_repo or {"consumers": [], "match_count": 0}
        finally:
            if settings.use_job_worktree:
                remove_job_worktree(job_id, repo_dir)

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
                "cross_repo_consumers": (cross_repo or {}).get("consumers") or [],
                "cross_repo": cross_repo,
            }
            job.changed_symbols = {
                "symbols": [s.qualified_name for s in report.suspect_functions],
                "suspects": payload["suspect_functions"],
                "line_ranges": payload["line_ranges"],
                "diff_summary": payload.get("diff_summary"),
                "head_commit_message": head_commit_message,
                "fullstack_impact": fullstack,
            }
            apply_gate_result(job, repo_rec)
            db.commit()
            notify_platform(job, repo_rec)

        return {"job_id": job_id, **payload}
    except Exception as exc:
        if job:
            job.status = "failed"
            msg = str(exc).strip()
            if is_worktree_path_only_error(msg) or (
                msg.startswith("D:") and "worktrees" in msg and len(msg) < 160
            ):
                msg = (
                    "分析沙箱 worktree 未成功挂载（历史任务可能只记录了路径）。"
                    "请在本页点击「重新分析」，并确认仓库 Git 凭据与 AST 索引正常。"
                )
            elif not msg or msg.startswith("D:"):
                msg = f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__
            job.error_message = msg[:2000]
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
            # 防抖定时器 / 启动恢复等在 HTTP 请求外触发，不能用已结束的 BackgroundTasks
            threading.Thread(target=run_analyze_merge, kwargs=kwargs, daemon=True).start()
            return {"runner": "thread", "task_id": None}
        background_tasks.add_task(run_analyze_merge, **kwargs)
        return {"runner": "background", "task_id": None}

    from app.tasks.analysis import analyze_merge_task

    task = analyze_merge_task.delay(**kwargs)
    return {"runner": "celery", "task_id": task.id}