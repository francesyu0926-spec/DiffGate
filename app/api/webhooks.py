import hashlib
import hmac
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.services.webhook_dispatch import dispatch_webhook_for_repos, find_webhook_targets
from app.services.webhook_pr_files import github_pr_changed_files, gitlab_mr_changed_files
from app.services.test_suite_webhook import enqueue_test_suite_sync_on_push
from app.services.webhook_scan_filter import github_push_changed_paths, gitlab_push_changed_paths

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

    changed_paths: list[str] | None = None
    extra_urls: list[str] = []

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
        if repo.get("ssh_url"):
            extra_urls.append(str(repo["ssh_url"]))
        full_name = repo["full_name"]
        pr_user = (pr.get("user") or {}).get("login") or ""
        pr_number = int(pr.get("number") or 0)
        job_metadata = {
            "pr_number": pr_number,
            "pr_url": pr.get("html_url"),
            "committer": pr_user,
            "commit_author_username": pr_user,
        }
        targets = find_webhook_targets(db, clone_url=clone_url, platform_full_name=full_name, extra_clone_urls=extra_urls)
        token = next(((r.access_token or "").strip() for r in targets if (r.access_token or "").strip()), None)
        if pr_number:
            files = github_pr_changed_files(clone_url=clone_url, pr_number=pr_number, token=token)
            changed_paths = files if files else []
        else:
            changed_paths = None
    else:
        commits = payload.get("commits") or []
        last = commits[-1] if commits else {}
        from app.api.webhook_meta import author_from_push_commit

        job_metadata = {
            "committer": ((payload.get("pusher") or {}).get("name")),
            **author_from_push_commit(last),
        }
        ref = payload.get("ref", "")
        if not ref.startswith("refs/heads/"):
            return {"ok": True, "ignored": ref}
        repo = payload["repository"]
        full_name = repo["full_name"]
        clone_url = repo["clone_url"]
        if repo.get("ssh_url"):
            extra_urls.append(str(repo["ssh_url"]))
        commits = payload.get("commits") or []
        if not commits:
            return {"ok": True, "ignored": "no commits"}
        head_sha = commits[-1]["id"]
        before = payload.get("before")
        base_sha = before if before and before != "0" * 40 else head_sha
        changed_paths = github_push_changed_paths(payload)

    ref_out = ref if isinstance(ref, str) and ref.startswith("refs/") else f"refs/heads/{ref}"
    if event == "push":
        enqueue_test_suite_sync_on_push(
            db,
            background_tasks,
            clone_url=clone_url,
            extra_clone_urls=extra_urls or None,
            ref=ref_out,
            changed_paths=changed_paths,
        )
    return dispatch_webhook_for_repos(
        db,
        background_tasks,
        provider="github",
        platform_full_name=full_name,
        clone_url=clone_url,
        base_sha=base_sha,
        head_sha=head_sha,
        ref=ref_out,
        job_metadata=job_metadata,
        changed_paths=changed_paths,
        extra_clone_urls=extra_urls or None,
    )


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
    changed_paths: list[str] | None = None
    extra_urls: list[str] = []
    job_metadata: dict | None = None

    if kind == "push":
        project = payload["project"]
        full_name = project["path_with_namespace"]
        clone_url = project["git_http_url"]
        if project.get("git_ssh_url"):
            extra_urls.append(str(project["git_ssh_url"]))
        ref = payload.get("ref", "")
        commits = payload.get("commits") or []
        if not commits:
            return {"ok": True, "ignored": "no commits"}
        head_sha = commits[-1]["id"]
        before = payload.get("before")
        base_sha = before if before and before != "0" * 40 else head_sha
        changed_paths = gitlab_push_changed_paths(payload)
        from app.api.webhook_meta import author_from_push_commit

        job_metadata = author_from_push_commit(commits[-1] if commits else None)
        user = payload.get("user_name") or payload.get("user_username")
        if user and job_metadata and not job_metadata.get("committer"):
            job_metadata["committer"] = str(user)
    elif kind == "merge_request":
        attrs = payload["object_attributes"]
        action = attrs.get("action")
        if action not in ("open", "update", "reopen"):
            return {"ok": True, "ignored": action}
        project = payload["project"]
        full_name = project["path_with_namespace"]
        clone_url = project["git_http_url"]
        if project.get("git_ssh_url"):
            extra_urls.append(str(project["git_ssh_url"]))
        ref = attrs.get("source_branch", "")
        base_sha = attrs["target_commit_sha"] or attrs.get("last_commit", {}).get("id", "")
        head_sha = attrs.get("last_commit", {}).get("id") or attrs.get("sha", "")
        if not head_sha:
            return {"ok": True, "ignored": "missing head sha"}
        mr_iid = int(attrs.get("iid") or 0)
        user = payload.get("user", {}) or {}
        uname = str(user.get("username") or user.get("name") or "").strip()
        job_metadata = {
            "pr_number": mr_iid or attrs.get("iid"),
            "committer": uname,
            "commit_author_username": uname,
            "commit_author_email": str(user.get("email") or "").strip(),
        }
        targets = find_webhook_targets(
            db, clone_url=clone_url, platform_full_name=full_name, extra_clone_urls=extra_urls
        )
        token = next(((r.access_token or "").strip() for r in targets if (r.access_token or "").strip()), None)
        web = str(project.get("web_url") or "https://gitlab.com")
        from urllib.parse import urlparse

        parsed = urlparse(web)
        gitlab_base = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else "https://gitlab.com"
        changed_paths = (
            gitlab_mr_changed_files(clone_url=clone_url, mr_iid=mr_iid, token=token, gitlab_base=gitlab_base)
            if mr_iid
            else []
        )
    else:
        return {"ok": True, "ignored": kind}

    ref_branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
    ref_out = ref if ref.startswith("refs/") else f"refs/heads/{ref_branch}"
    if kind == "push":
        enqueue_test_suite_sync_on_push(
            db,
            background_tasks,
            clone_url=clone_url,
            extra_clone_urls=extra_urls or None,
            ref=ref_out,
            changed_paths=changed_paths,
        )
    return dispatch_webhook_for_repos(
        db,
        background_tasks,
        provider="gitlab",
        platform_full_name=full_name,
        clone_url=clone_url,
        base_sha=base_sha,
        head_sha=head_sha,
        ref=ref_out,
        job_metadata=job_metadata,
        changed_paths=changed_paths,
        extra_clone_urls=extra_urls or None,
    )