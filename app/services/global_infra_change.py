"""全局配置类变更：影响面过大时标注基础设施变更并建议全量冒烟。"""

from __future__ import annotations

import fnmatch
from typing import Any

from app.db.models import AnalysisJob, Repository
from app.services.high_risk_paths import changed_paths_from_job

_BLAST_RATIO = 0.5

_GLOBAL_INFRA_GLOBS = (
    "**/settings.py",
    "**/database.py",
    "**/db.py",
    "**/middleware.py",
    "**/main.py",
    "**/config.py",
    "**/core/config*.py",
)


def _matches_global_infra(path: str) -> bool:
    norm = path.replace("\\", "/").lstrip("./")
    base = norm.rsplit("/", 1)[-1]
    for pat in _GLOBAL_INFRA_GLOBS:
        if fnmatch.fnmatch(norm, pat) or fnmatch.fnmatch(base, pat.rsplit("/", 1)[-1]):
            return True
    return False


def detect_global_infrastructure_change(
    job: AnalysisJob,
    repo: Repository | None,
) -> dict[str, Any] | None:
    paths = changed_paths_from_job(job)
    if not any(_matches_global_infra(p) for p in paths):
        return None
    affected = job.affected_apis or {}
    api_n = len(affected.get("apis") or [])
    total = int(getattr(repo, "ast_api_count", 0) or 0) if repo else 0
    if total <= 0:
        return None
    ratio = api_n / total
    if ratio < _BLAST_RATIO:
        return None
    return {
        "label": "全局基础设施变更",
        "hint": "建议执行全量核心冒烟集",
        "affected_api_count": api_n,
        "repo_api_total": total,
        "affected_api_ratio": round(ratio, 3),
        "matched_paths": [p for p in paths if _matches_global_infra(p)][:20],
        "trace_capped": True,
    }


def apply_global_infrastructure_annotation(job: AnalysisJob, repo: Repository | None) -> None:
    meta = detect_global_infrastructure_change(job, repo)
    if not meta:
        return
    symbols = dict(job.changed_symbols or {})
    symbols["global_infrastructure_change"] = meta
    job.changed_symbols = symbols
    affected = dict(job.affected_apis or {})
    paths = affected.get("call_paths") or []
    cap = max(40, int((repo.ast_api_count if repo else 80) * _BLAST_RATIO))
    if len(paths) > cap:
        affected["call_paths"] = paths[:cap]
        affected["call_paths_truncated"] = True
    apis = affected.get("apis") or []
    if len(apis) > cap:
        affected["apis"] = apis[:cap]
        affected["apis_truncated"] = True
    job.affected_apis = affected