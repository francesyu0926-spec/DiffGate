"""前端索引/分析完成后，刷新关联后端批次的契约门禁缓存。"""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import AnalysisJob, Repository
from app.services.contract_impact import (
    _contract_key,
    _frontend_consumers_for_keys,
    enrich_cross_repo,
)
from app.services.quality_gate import apply_gate_result


def _backend_repos_linked_to_frontend(db: Session, frontend_repo: Repository) -> list[Repository]:
    out: list[Repository] = []
    for repo in db.scalars(select(Repository).where(Repository.enabled.is_(True))).all():
        if (repo.repo_type or "backend") == "frontend":
            continue
        linked = list(repo.linked_repo_ids or [])
        if frontend_repo.id in linked:
            out.append(repo)
    return out


def _reevaluate_breaking_hits(
    db: Session,
    backend_repo: Repository,
    contract_impact: dict,
) -> dict:
    """用最新前端索引缓存重算 breaking_hits。"""
    ci = dict(contract_impact)
    keys: set[str] = set()
    for r in ci.get("route_removals") or []:
        if isinstance(r, dict):
            keys.add(_contract_key(str(r.get("method") or "GET"), str(r.get("path") or "/")))
    for m in ci.get("route_modifications") or []:
        if isinstance(m, dict):
            keys.add(_contract_key(str(m.get("old_method") or "GET"), str(m.get("old_path") or "/")))
    if not keys:
        return ci
    impacts = _frontend_consumers_for_keys(db, backend_repo, keys)
    breaking: list[dict] = []
    warnings: list[dict] = []
    for hit in impacts:
        row = dict(hit)
        matched = False
        for r in ci.get("route_removals") or []:
            if isinstance(r, dict) and hit.get("contract_key") == _contract_key(
                str(r.get("method") or "GET"), str(r.get("path") or "/")
            ):
                row = {**row, **r}
                matched = True
        for mod in ci.get("route_modifications") or []:
            if isinstance(mod, dict) and hit.get("contract_key") == _contract_key(
                str(mod.get("old_method") or "GET"), str(mod.get("old_path") or "/")
            ):
                row = {**row, **mod}
                matched = True
        if not matched:
            continue
        if hit.get("dynamic"):
            warnings.append(row)
        else:
            breaking.append(row)
    ci["impacts"] = impacts
    ci["breaking_hits"] = breaking
    ci["warnings"] = warnings
    return ci


def refresh_linked_backend_contract_gates(
    db: Session,
    *,
    frontend_repo: Repository,
    limit_per_backend: int = 30,
) -> int:
    """清除因前端索引滞后导致的 stale breaking 拦截。"""
    backends = _backend_repos_linked_to_frontend(db, frontend_repo)
    if not backends:
        return 0
    refreshed = 0
    for be in backends:
        jobs = list(
            db.scalars(
                select(AnalysisJob)
                .where(
                    AnalysisJob.repo_full_name == be.full_name,
                    AnalysisJob.status == "completed",
                )
                .order_by(desc(AnalysisJob.created_at))
                .limit(limit_per_backend)
            ).all()
        )
        for job in jobs:
            gr = job.gate_result or {}
            if gr.get("block_reason") != "breaking_contract_change":
                continue
            aa = job.affected_apis or {}
            cross = aa.get("cross_repo") if isinstance(aa.get("cross_repo"), dict) else {}
            ci = cross.get("contract_impact") if isinstance(cross, dict) else None
            if not isinstance(ci, dict):
                continue
            new_ci = _reevaluate_breaking_hits(db, be, ci)
            enrich_cross_repo(job, be, new_ci)
            apply_gate_result(job, be)
            refreshed += 1
    if refreshed:
        db.commit()
    return refreshed