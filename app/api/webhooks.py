import hashlib
import hmac
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AnalysisJob
from app.db.session import get_db
from app.services.repo_registry import ensure_registered
from app.services.analysis_runner import schedule_analyze_merge

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_github_signature(body: bytes, signature: str | None, secret: str) -> None:
    if not secret:
        return
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing GitHub signature")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={expected}", signature):
        raise HTTPException(status_code=401, detail="Invalid GitHub signature")


def _verify_gitlab_token(token: str | None, secret: str) -> None:
    if not secret:
        return
    if token != secret:
        raise HTTPException(status_code=401, detail="Invalid GitLab token")


def _enqueue_job(
    db: Session,
    background_tasks: BackgroundTasks,
    provider: str,
    repo_full_name: str,
    clone_url: str,
    base_sha: str,
    head_sha: str,
    ref: str,
) -> tuple[str, str | None]:
    job_id = str(uuid.uuid4())
    job = AnalysisJob(
        id=job_id,
        provider=provider,
        repo_full_name=repo_full_name,
        ref=ref,
        base_sha=base_sha,
        head_sha=head_sha,
        status="pending",
    )
    db.add(job)
    db.commit()
    meta = schedule_analyze_merge(
        background_tasks=background_tasks,
        job_id=job_id,
        provider=provider,
        repo_full_name=repo_full_name,
        clone_url=clone_url,
        base_sha=base_sha,
        head_sha=head_sha,
        ref=ref,
    )
    return job_id, meta.get("task_id")


@router.get("/github")
def github_webhook_probe() -> dict[str, str]:
    """供 GitHub 添加 Webhook 时的 URL 可达性探测（正式事件仍走 POST）。"""
    return {"ok": "true", "method": "POST", "events": "push,pull_request"}


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
) -> dict[str, Any]:
    settings = get_settings()
    body = await request.body()
    _verify_github_signature(body, x_hub_signature_256, settings.webhook_secret_github)

    import json

    payload = json.loads(body)
    event = x_github_event or ""

    if event == "ping":
        return {"ok": True, "message": "pong"}

    if event not in ("pull_request", "push"):
        return {"ok": True, "ignored": event}

    if event == "pull_request":
        action = payload.get("action")
        if action not in ("opened", "synchronize", "reopened"):
            return {"ok": True, "ignored": action}
        pr = payload["pull_request"]
        repo = payload["repository"]
        base_sha = pr["base"]["sha"]
        head_sha = pr["head"]["sha"]
        ref = pr["head"]["ref"]
        clone_url = repo["clone_url"]
        full_name = repo["full_name"]
    else:
        ref = payload.get("ref", "")
        if not ref.startswith("refs/heads/"):
            return {"ok": True, "ignored": ref}
        repo = payload["repository"]
        full_name = repo["full_name"]
        clone_url = repo["clone_url"]
        commits = payload.get("commits") or []
        if not commits:
            return {"ok": True, "ignored": "no commits"}
        head_sha = commits[-1]["id"]
        before = payload.get("before")
        base_sha = before if before and before != "0" * 40 else head_sha

    ref_branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
    if ensure_registered(db, provider="github", full_name=full_name, clone_url=clone_url, default_branch=ref_branch) is None:
        return {"ok": True, "ignored": "repository disabled or webhook off"}
    job_id, task_id = _enqueue_job(
        db, background_tasks, "github", full_name, clone_url, base_sha, head_sha, ref
    )
    out: dict[str, Any] = {"ok": True, "job_id": job_id}
    if task_id:
        out["celery_task_id"] = task_id
    return out


@router.get("/gitlab")
def gitlab_webhook_probe() -> dict[str, str]:
    return {"ok": "true", "method": "POST"}


@router.post("/gitlab")
async def gitlab_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_gitlab_token: str | None = Header(None),
) -> dict[str, Any]:
    settings = get_settings()
    _verify_gitlab_token(x_gitlab_token, settings.webhook_secret_gitlab)
    payload = await request.json()

    kind = payload.get("object_kind")
    if kind == "push":
        project = payload["project"]
        full_name = project["path_with_namespace"]
        clone_url = project["git_http_url"]
        ref = payload.get("ref", "")
        commits = payload.get("commits") or []
        if not commits:
            return {"ok": True, "ignored": "no commits"}
        head_sha = commits[-1]["id"]
        before = payload.get("before")
        base_sha = before if before and before != "0" * 40 else head_sha
    elif kind == "merge_request":
        attrs = payload["object_attributes"]
        action = attrs.get("action")
        if action not in ("open", "update", "reopen"):
            return {"ok": True, "ignored": action}
        project = payload["project"]
        full_name = project["path_with_namespace"]
        clone_url = project["git_http_url"]
        ref = attrs.get("source_branch", "")
        base_sha = attrs["target_commit_sha"] or attrs.get("last_commit", {}).get("id", "")
        head_sha = attrs.get("last_commit", {}).get("id") or attrs.get("sha", "")
        if not head_sha:
            return {"ok": True, "ignored": "missing head sha"}
    else:
        return {"ok": True, "ignored": kind}

    ref_branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
    if ensure_registered(db, provider="gitlab", full_name=full_name, clone_url=clone_url, default_branch=ref_branch) is None:
        return {"ok": True, "ignored": "repository disabled or webhook off"}
    job_id, task_id = _enqueue_job(
        db, background_tasks, "gitlab", full_name, clone_url, base_sha, head_sha, ref
    )
    out: dict[str, Any] = {"ok": True, "job_id": job_id}
    if task_id:
        out["celery_task_id"] = task_id
    return out