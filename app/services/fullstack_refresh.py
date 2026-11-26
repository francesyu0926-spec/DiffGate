"""对已完成作业补算全栈追溯（无需重跑 AST）。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AnalysisJob, Repository
from app.graph.stores import cache_job_graph, load_job_graph
from app.graph.viz import augment_graph_with_frontend, sanitize_graph_paths, strip_frontend_layer
from app.parsers.frontend_trace import build_fullstack_impact
from app.services.cross_repo_trace import find_cross_repo_consumers


def refresh_job_fullstack(db: Session, job: AnalysisJob) -> dict:
    settings = get_settings()
    _ = db.scalar(select(Repository).where(Repository.full_name == job.repo_full_name))
    safe = job.repo_full_name.replace("/", "_")
    repo_dir = (Path(settings.repo_clone_root) / safe).resolve()
    if not repo_dir.is_dir():
        raise FileNotFoundError(f"本地克隆不存在: {repo_dir}")

    apis = (job.affected_apis or {}).get("apis") or []
    changed = {
        lr.get("path")
        for lr in (job.changed_symbols or {}).get("line_ranges") or []
        if isinstance(lr, dict) and lr.get("path")
    }
    fullstack = build_fullstack_impact(
        repo_dir,
        changed,
        scan_roots=("frontend", "web", "src", "."),
        backend_apis=apis,
    )
    base_graph = load_job_graph(job.id) or {}
    if base_graph.get("nodes"):
        base_graph = sanitize_graph_paths(strip_frontend_layer(base_graph))
        cache_job_graph(job.id, augment_graph_with_frontend(base_graph, fullstack, apis))

    api_paths = [str(a.get("path") or "") for a in apis]
    fe_paths = [str(c.get("path") or "") for c in fullstack.get("frontend_api_calls") or []]
    cross_repo = find_cross_repo_consumers(
        db,
        provider_repo=job.repo_full_name,
        provider_api_paths=api_paths,
        extra_paths=fe_paths,
    )

    cs = dict(job.changed_symbols or {})
    cs["fullstack_impact"] = fullstack
    job.changed_symbols = cs
    aa = dict(job.affected_apis or {})
    aa["cross_repo_consumers"] = cross_repo.get("consumers") or []
    aa["cross_repo"] = cross_repo
    job.affected_apis = aa
    db.commit()
    return {"fullstack_impact": fullstack, "cross_repo": cross_repo}