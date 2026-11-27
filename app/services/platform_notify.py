"""GitHub/GitLab 状态回写与 IM 告警（BLOCK 时）。"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.db.models import AnalysisJob, Repository

logger = logging.getLogger(__name__)


def _uncovered_lines(gr: dict) -> list[str]:
    lines: list[str] = []
    for row in gr.get("coverage_probes") or []:
        if not isinstance(row, dict) or row.get("covered"):
            continue
        f = row.get("file")
        ln = row.get("line")
        if f and ln:
            lines.append(f"`{f}:{ln}`")
    return lines[:40]


def _build_pr_comment(job: AnalysisJob, gr: dict) -> str:
    gate = gr.get("gate") or "PENDING"
    apis = (job.affected_apis or {}).get("apis") or []
    api_lines = [
        f"- `{a.get('method', 'GET')} {a.get('path', '/')}` ({a.get('handler', '')})"
        for a in apis[:30]
    ]
    cov = gr.get("incremental_coverage_pct")
    cov_s = f"{cov}%" if cov is not None else "待回传"
    missed = _uncovered_lines(gr)
    body = [
        "## DiffGate 质量门禁",
        "",
        f"**结果**: `{gate}`" + (f" — {gr.get('gate_label')}" if gr.get("gate_label") else ""),
        f"**增量覆盖率**: {cov_s}（阈值 {gr.get('coverage_threshold')}%）",
    ]
    if gr.get("path_gate_rule"):
        body.append(f"**路径规则**: `{gr['path_gate_rule']}`")
    body.extend(["", "### 受影响 API", ""])
    body.extend(api_lines or ["- （无）"])
    if missed:
        body.extend(["", "### 漏测行", "", ", ".join(missed)])
    body.append("")
    body.append(f"Job: `{job.id}` · Commit `{ (job.head_sha or '')[:8]}`")
    return "\n".join(body)


def _github_status_state(gate: str) -> str:
    g = (gate or "PENDING").upper()
    if g in ("PASS", "OVERRIDDEN"):
        return "success"
    if g == "BLOCK":
        return "failure"
    return "pending"


def notify_github(job: AnalysisJob, repo: Repository | None, gr: dict) -> None:
    settings = get_settings()
    if not settings.github_token:
        return
    meta = job.job_metadata or {}
    sha = job.head_sha
    if not sha:
        return
    state = _github_status_state(str(gr.get("gate")))
    desc = gr.get("block_reason_label") or f"DiffGate {gr.get('gate')}"
    owner, _, name = job.repo_full_name.partition("/")
    if not owner or not name:
        return
    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
    }
    ctx = "diffgate/quality-gate"
    status_url = (
        f"https://api.github.com/repos/{owner}/{name}/statuses/{sha}"
    )
    try:
        with httpx.Client(timeout=30.0) as client:
            client.post(
                status_url,
                headers=headers,
                json={
                    "state": state,
                    "description": desc[:140],
                    "context": ctx,
                    "target_url": meta.get("target_url"),
                },
            )
            pr = meta.get("pr_number")
            if pr and settings.github_pr_comments:
                comment = _build_pr_comment(job, gr)
                client.post(
                    f"https://api.github.com/repos/{owner}/{name}/issues/{pr}/comments",
                    headers=headers,
                    json={"body": comment},
                )
    except Exception as exc:
        logger.warning("github notify failed: %s", exc)


def notify_gitlab(job: AnalysisJob, repo: Repository | None, gr: dict) -> None:
    settings = get_settings()
    token = repo.access_token if repo and repo.access_token else settings.gitlab_token
    if not token:
        return
    sha = job.head_sha
    project = job.repo_full_name.replace("/", "%2F")
    state = _github_status_state(str(gr.get("gate")))
    gl_state = {"success": "success", "failure": "failed", "pending": "running"}[state]
    try:
        with httpx.Client(timeout=30.0) as client:
            client.post(
                f"https://gitlab.com/api/v4/projects/{project}/statuses",
                headers={"PRIVATE-TOKEN": token},
                json={
                    "sha": sha,
                    "state": gl_state,
                    "name": "diffgate/quality-gate",
                    "description": (gr.get("block_reason_label") or str(gr.get("gate")))[:140],
                },
            )
    except Exception as exc:
        logger.warning("gitlab notify failed: %s", exc)


def notify_im_block(job: AnalysisJob, repo: Repository | None, gr: dict) -> dict | None:
    from app.services.im_notify import send_gate_im_notice

    return send_gate_im_notice(job, repo, gr)


def notify_platform(job: AnalysisJob, repo: Repository | None) -> None:
    gr = dict(job.gate_result or {})
    if job.provider == "github":
        notify_github(job, repo, gr)
    elif job.provider == "gitlab":
        notify_gitlab(job, repo, gr)
    notify_status = notify_im_block(job, repo, gr)
    if notify_status is not None:
        gr["notify_status"] = notify_status
        job.gate_result = gr