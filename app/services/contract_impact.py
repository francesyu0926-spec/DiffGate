"""双仓契约影响：后端 ↔ 前端、破坏性变更检测。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnalysisJob, Repository
from app.graph.neo4j_contracts import contract_key_http
from app.parsers.frontend_contract import normalize_frontend_api_path, resolve_api_path_align
from app.parsers.http_client_scan import normalize_contract_path
from app.services.frontend_index_cache import load_frontend_index

_ROUTE_DEC_RE = re.compile(
    r"@\w+\.(get|post|put|patch|delete|head|options)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


def linked_repositories(db: Session, repo: Repository) -> list[Repository]:
    ids = list(repo.linked_repo_ids or [])
    if not ids:
        return []
    rows = list(db.scalars(select(Repository).where(Repository.id.in_(ids), Repository.enabled.is_(True))))
    return rows


def _contract_key(method: str, path: str) -> str:
    return contract_key_http((method or "GET").upper(), normalize_contract_path(path))


def _paths_equivalent(a: str, b: str) -> bool:
    na = normalize_frontend_api_path(a)
    nb = normalize_frontend_api_path(b)
    return na == nb or na.endswith(nb) or nb.endswith(na)


def _frontend_consumers_for_keys(
    db: Session,
    provider: Repository,
    contract_keys: set[str],
) -> list[dict[str, Any]]:
    """在关联前端仓索引中查找命中契约的页面/调用点。"""
    out: list[dict[str, Any]] = []
    for fe in linked_repositories(db, provider):
        if (fe.repo_type or "backend") != "frontend":
            continue
        cached = load_frontend_index(fe.id)
        if not cached:
            continue
        align = resolve_api_path_align(fe)
        for row in cached.get("api_calls_norm") or []:
            method = (row.get("method") or "GET").upper()
            path_norm = row.get("path_norm") or normalize_frontend_api_path(
                row.get("path") or "", align=align
            )
            ck = _contract_key(method, path_norm)
            if ck not in contract_keys:
                continue
            conf = float(row.get("confidence") or 0.9)
            out.append(
                {
                    "frontend_repo_id": fe.id,
                    "frontend_repo": fe.full_name,
                    "page_file": row.get("file"),
                    "line": row.get("line"),
                    "method": method,
                    "api_path": path_norm,
                    "contract_key": ck,
                    "confidence": conf,
                    "dynamic": conf < 0.7,
                }
            )
    return out


def parse_git_route_removals(repo_path: Path, base_sha: str, head_sha: str) -> list[dict[str, Any]]:
    """从 git diff 提取被删除的 FastAPI 路由装饰器。"""
    repo_path = repo_path.resolve()
    try:
        proc = subprocess.run(
            ["git", "diff", f"{base_sha}..{head_sha}", "-U0", "--", "*.py"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0 and not proc.stdout:
        return []
    removed: list[dict[str, Any]] = []
    current_file: str | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
        elif line.startswith("--- a/"):
            continue
        if not line.startswith("-") or line.startswith("---"):
            continue
        body = line[1:].strip()
        m = _ROUTE_DEC_RE.search(body)
        if m and current_file:
            removed.append(
                {
                    "method": m.group(1).upper(),
                    "path": m.group(2),
                    "file": current_file,
                    "change_type": "route_removed",
                }
            )
    return removed


def parse_git_route_modifications(repo_path: Path, base_sha: str, head_sha: str) -> list[dict[str, Any]]:
    """同文件内路由装饰器 method/path 被替换。"""
    try:
        proc = subprocess.run(
            ["git", "diff", f"{base_sha}..{head_sha}", "--", "*.py"],
            cwd=str(repo_path.resolve()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    changes: list[dict[str, Any]] = []
    current_file: str | None = None
  # omit diff hunk wiring
    for line in proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
        if line.startswith("-") and not line.startswith("---"):
            m = _ROUTE_DEC_RE.search(line[1:])
            if m and current_file:
                changes.append(
                    {
                        "method": m.group(1).upper(),
                        "path": m.group(2),
                        "file": current_file,
                        "side": "old",
                    }
                )
        elif line.startswith("+") and not line.startswith("+++"):
            m = _ROUTE_DEC_RE.search(line[1:])
            if m and current_file:
                changes.append(
                    {
                        "method": m.group(1).upper(),
                        "path": m.group(2),
                        "file": current_file,
                        "side": "new",
                    }
                )
    modified: list[dict[str, Any]] = []
    olds = [c for c in changes if c.get("side") == "old"]
    news = [c for c in changes if c.get("side") == "new"]
    for o in olds:
        pair = next(
            (n for n in news if n.get("file") == o.get("file") and (n.get("path") != o.get("path") or n.get("method") != o.get("method"))),
            None,
        )
        if pair:
            modified.append(
                {
                    "change_type": "route_modified",
                    "file": o.get("file"),
                    "old_method": o.get("method"),
                    "old_path": o.get("path"),
                    "new_method": pair.get("method"),
                    "new_path": pair.get("path"),
                }
            )
    return modified


def evaluate_backend_contract_impact(
    db: Session,
    *,
    job: AnalysisJob,
    repo: Repository,
    repo_path: Path,
    base_sha: str,
    head_sha: str,
    affected_apis: list[dict],
) -> dict[str, Any]:
    removals = parse_git_route_removals(repo_path, base_sha, head_sha)
    modifications = parse_git_route_modifications(repo_path, base_sha, head_sha)
    contract_keys: set[str] = set()
    for r in removals:
        contract_keys.add(_contract_key(r["method"], r["path"]))
    for m in modifications:
        contract_keys.add(_contract_key(str(m.get("old_method") or "GET"), str(m.get("old_path") or "/")))

    impacts = _frontend_consumers_for_keys(db, repo, contract_keys)
    breaking_hits: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def _classify(hit: dict, change: dict) -> None:
        row = {**hit, **change}
        if hit.get("dynamic"):
            warnings.append(row)
        else:
            breaking_hits.append(row)

    for r in removals:
        ck = _contract_key(r["method"], r["path"])
        for hit in impacts:
            if hit.get("contract_key") == ck:
                _classify(hit, r)

    for m in modifications:
        ck = _contract_key(str(m.get("old_method") or "GET"), str(m.get("old_path") or "/"))
        for hit in impacts:
            if hit.get("contract_key") == ck:
                _classify(hit, m)

    for api in affected_apis or []:
        if not isinstance(api, dict):
            continue
        for hit in impacts:
            if _paths_equivalent(hit.get("api_path") or "", api.get("path") or ""):
                if hit.get("dynamic"):
                    warnings.append({**hit, "change_type": "api_impact_linked"})
                else:
                    breaking_hits.append({**hit, "change_type": "api_impact_linked"})

    return {
        "perspective": "backend",
        "impacts": impacts,
        "breaking_hits": breaking_hits,
        "warnings": warnings,
        "route_removals": removals,
        "route_modifications": modifications,
        "linked_repo_count": len(linked_repositories(db, repo)),
    }


def _backend_repos_for_frontend(db: Session, fe_repo: Repository) -> list[Repository]:
    linked = linked_repositories(db, fe_repo)
    backs = [r for r in linked if (r.repo_type or "backend") != "frontend"]
    if backs:
        return backs
    return list(
        db.scalars(
            select(Repository).where(
                Repository.enabled.is_(True),
                Repository.full_name != fe_repo.full_name,
            )
        ).all()
    )[:5]


def evaluate_frontend_contract_impact(
    db: Session,
    *,
    repo: Repository,
    fullstack: dict | None,
) -> dict[str, Any]:
    fullstack = fullstack or {}
    calls = fullstack.get("frontend_api_calls") or fullstack.get("matched_api_calls") or []
    align = resolve_api_path_align(repo)
    contract_keys: list[str] = []
    normalized: list[dict[str, Any]] = []
    for row in calls:
        if not isinstance(row, dict):
            continue
        method = (row.get("method") or "GET").upper()
        path = normalize_frontend_api_path(row.get("path") or row.get("url") or "", align=align)
        ck = _contract_key(method, path)
        contract_keys.append(ck)
        normalized.append({**row, "path_norm": path, "contract_key": ck})

    backends = _backend_repos_for_frontend(db, repo)
    suggested_cases: list[dict[str, Any]] = []
    for be in backends:
        if (be.repo_type or "backend") == "frontend":
            continue
        for ck in sorted(set(contract_keys)):
            segs = ck.split(":", 2)
            m = segs[1] if len(segs) > 2 else "GET"
            route = segs[2] if len(segs) > 2 else "/"
            safe = route.strip("/").replace("/", "_").replace("*", "x") or "root"
            suggested_cases.append(
                {
                    "backend_repo_id": be.id,
                    "backend_repo": be.full_name,
                    "method": m,
                    "path": route,
                    "contract_key": ck,
                    "yaml_file": f"cases/{m.lower()}_{safe}.yaml",
                    "test_suite_id": be.test_suite_id,
                }
            )

    return {
        "perspective": "frontend",
        "impacts": normalized,
        "breaking_hits": [],
        "warnings": [c for c in normalized if c.get("dynamic")],
        "suggested_regression_cases": suggested_cases,
        "contract_keys": sorted(set(contract_keys)),
        "linked_backend_count": len(backends),
    }


def enrich_cross_repo(db: Session, job: AnalysisJob, repo: Repository | None, contract: dict) -> None:
    """写回 job.affected_apis.cross_repo.contract_impact。"""
    if not repo:
        return
    aa = dict(job.affected_apis or {})
    cross = dict(aa.get("cross_repo") or {})
    cross["contract_impact"] = contract
    aa["cross_repo"] = cross
    job.affected_apis = aa