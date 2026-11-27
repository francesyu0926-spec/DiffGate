"""仓库分支探测：本地 → GitHub/GitLab API（并行）→ git ls-remote --symref，总超时 8s。"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from urllib.parse import quote

import httpx
from git import Repo
from sqlalchemy.orm import Session

from app.db.models import Repository, TestSuite
from app.services.git_branches import list_repository_branches
from app.services.git_clone import _normalize_local_clone_url, git_ssh_command_for_repo, inject_access_token
from app.services.git_credential_chain import GitCredentialResolution, resolve_git_clone_credentials
from app.services.gitlab_private import encode_gitlab_project_from_meta, gitlab_api_base, resolve_git_ssl_verify
from app.services.repo_detect_parse import is_local_clone_url, parse_clone_url_meta
from app.services.repo_detect_remote import _github_headers, _gitlab_headers

DetectSource = Literal["local_git", "linked_repo", "github_api", "gitlab_api", "git_ls_remote", "none"]
CredentialMode = Literal["auto", "token", "ssh"]

_DETECT_TIMEOUT_SEC = 8.0
_HTTP_TIMEOUT_SEC = 5.0
_LS_REMOTE_TIMEOUT_SEC = 8.0

_SYMREF_RE = re.compile(r"^ref:\s+refs/heads/(\S+)\s+HEAD$")
_HEAD_RE = re.compile(r"^[0-9a-f]+\s+refs/heads/(\S+)$", re.I)
# git stderr 常含带凭据的 clone URL（oauth2:TOKEN@、x-access-token:TOKEN@ 等）
_URL_EMBEDDED_CRED_RE = re.compile(r"(https?://)[^/\s@:]+:[^@\s/]+@", re.I)


def _auth_method_from_mode(mode: str | None) -> str:
    m = (mode or "auto").lower()
    if m == "token":
        return "token"
    if m == "ssh":
        return "ssh"
    return "inherit"


def _redact_secrets(text: str, *secrets: str | None) -> str:
    out = text
    for raw in secrets:
        if not raw:
            continue
        token = raw.strip()
        if not token:
            continue
        out = out.replace(token, "***").replace(quote(token, safe=""), "***")
    return out


def _sanitize_error_message(text: str | None, *secrets: str | None) -> str | None:
    """脱敏：明文 token + URL 内嵌凭据，避免泄露到前端/日志。"""
    if not text:
        return text
    out = _redact_secrets(text, *secrets)
    out = _URL_EMBEDDED_CRED_RE.sub(r"\1***:***@", out)
    return out


def _order_branches(names: list[str], default_branch: str) -> tuple[str, list[str]]:
    default = (default_branch or "main").strip() or "main"
    unique = sorted({n.strip() for n in names if (n or "").strip()}, key=str.lower)
    if default not in unique:
        unique.append(default)
        unique = sorted(set(unique), key=str.lower)
    if default in unique:
        ordered = [default] + [n for n in unique if n != default]
    else:
        ordered = unique
        default = ordered[0] if ordered else "main"
    return default, ordered


def _response(
    *,
    success: bool,
    source: DetectSource,
    default_branch: str,
    branch_names: list[str],
    error_message: str | None = None,
) -> dict:
    default, ordered = _order_branches(branch_names, default_branch)
    branches = [{"name": n, "is_default": n == default} for n in ordered]
    return {
        "success": success,
        "source": source,
        "default_branch": default,
        "branches": branches,
        "error_message": _sanitize_error_message(error_message),
    }


async def _local_branches_async(clone_url: str) -> tuple[list[str], str]:
    raw = _normalize_local_clone_url(clone_url)
    root = Path(raw).expanduser().resolve()
    default = "main"
    if not root.exists() or not root.is_dir():
        return [default], default
    if not (root / ".git").is_dir():
        return [default], default
    local_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(root),
        "branch",
        "-a",
        "--format=%(refname:short)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=local_env,
    )
    stdout, _ = await proc.communicate()
    names: set[str] = set()
    for line in stdout.decode("utf-8", errors="ignore").splitlines():
        short = line.strip().removeprefix("remotes/origin/").strip()
        if short and short != "HEAD":
            names.add(short)
    if not names:
        git = Repo(str(root))
        names = {h.name for h in git.heads}
        for remote in git.remotes:
            for ref in remote.refs:
                short = ref.name.split("/", 1)[-1] if "/" in ref.name else ref.name
                if short != "HEAD":
                    names.add(short)
    if not names:
        names.add(default)
    items = sorted(names, key=str.lower)
    if "main" in items:
        default = "main"
    elif "master" in items:
        default = "master"
    else:
        default = items[0]
    return items, default


async def _try_github_api_async(meta, token: str | None) -> dict | None:
    headers = _github_headers(token)
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as client:
            repo_task = client.get(
                f"https://api.github.com/repos/{meta.owner}/{meta.repo_name}",
                headers=headers,
            )
            branch_task = client.get(
                f"https://api.github.com/repos/{meta.owner}/{meta.repo_name}/branches",
                headers=headers,
                params={"per_page": 100},
            )
            repo_resp, branch_resp = await asyncio.gather(repo_task, branch_task)
            if branch_resp.status_code != 200:
                return None
            default = "main"
            if repo_resp.status_code == 200:
                default = str(repo_resp.json().get("default_branch") or "main")
            chunk = branch_resp.json()
            names = [str(b.get("name") or "").strip() for b in chunk if isinstance(b, dict)]
            names = [n for n in names if n]
            return _response(
                success=True,
                source="github_api",
                default_branch=default,
                branch_names=names,
            )
    except Exception:
        return None


async def _try_gitlab_api_async(
    meta,
    token: str | None,
    *,
    clone_url: str,
    verify_ssl: bool,
) -> dict | None:
    api_base = gitlab_api_base(meta).rstrip("/")
    enc = encode_gitlab_project_from_meta(meta)
    ssl_verify = resolve_git_ssl_verify(clone_url, not verify_ssl)
    headers = _gitlab_headers(token)
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC, verify=ssl_verify) as client:
            proj_task = client.get(f"{api_base}/api/v4/projects/{enc}", headers=headers)
            branch_task = client.get(
                f"{api_base}/api/v4/projects/{enc}/repository/branches",
                headers=headers,
                params={"per_page": 100},
            )
            proj_resp, branch_resp = await asyncio.gather(proj_task, branch_task)
            if branch_resp.status_code != 200:
                return None
            default = "main"
            if proj_resp.status_code == 200:
                default = str(proj_resp.json().get("default_branch") or "main")
            chunk = branch_resp.json()
            names = [str(b.get("name") or "").strip() for b in chunk if isinstance(b, dict)]
            names = [n for n in names if n]
            return _response(
                success=True,
                source="gitlab_api",
                default_branch=default,
                branch_names=names,
            )
    except Exception:
        return None


def _parse_ls_remote_symref(stdout: str) -> tuple[list[str], str]:
    default = "main"
    names: list[str] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        sym = _SYMREF_RE.match(stripped)
        if sym:
            default = sym.group(1)
            continue
        head = _HEAD_RE.match(stripped)
        if head:
            names.append(head.group(1))
    if not names:
        return [default], default
    if default not in names:
        if "main" in names:
            default = "main"
        elif "master" in names:
            default = "master"
        else:
            default = names[0]
    return names, default


async def _detect_via_ls_remote_async(
    clone_url: str,
    creds: GitCredentialResolution,
    *,
    verify_ssl: bool,
) -> dict:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if not verify_ssl:
        env["GIT_SSL_NO_VERIFY"] = "true"

    effective_url = clone_url
    token = (creds.access_token or "").strip() if creds.auth_method == "token" else ""
    ssh_key = (creds.ssh_private_key or "").strip() if creds.auth_method == "ssh" else ""

    if token and clone_url.startswith(("http://", "https://")):
        effective_url = inject_access_token(clone_url, token, creds.provider)

    pseudo = None
    if ssh_key:
        pseudo = SimpleNamespace(
            id=f"br-detect-{uuid.uuid4().hex[:10]}",
            auth_method="ssh",
            ssh_private_key=ssh_key,
        )

    try:
        with git_ssh_command_for_repo(pseudo) as ssh_cmd:
            if ssh_cmd:
                env["GIT_SSH_COMMAND"] = ssh_cmd
            proc = await asyncio.create_subprocess_exec(
                "git",
                "ls-remote",
                "--symref",
                effective_url,
                "HEAD",
                "refs/heads/*",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_LS_REMOTE_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        return _response(
            success=False,
            source="git_ls_remote",
            default_branch="main",
            branch_names=[],
            error_message="连接仓库超时（8秒），请检查内网连通性或端口",
        )

    if proc.returncode != 0:
        err_text = stderr.decode("utf-8", errors="ignore").strip() or stdout.decode("utf-8", errors="ignore").strip()
        err_text = _sanitize_error_message(err_text, token, ssh_key) or "拉取分支失败：认证失败或地址不可达"
        return _response(
            success=False,
            source="git_ls_remote",
            default_branch="main",
            branch_names=[],
            error_message=err_text or "拉取分支失败：认证失败或地址不可达",
        )

    output = stdout.decode("utf-8", errors="ignore")
    names, default = _parse_ls_remote_symref(output)
    return _response(
        success=True,
        source="git_ls_remote",
        default_branch=default,
        branch_names=names,
    )


async def _detect_impl_async(
    db: Session,
    *,
    clone_url: str,
    credential_mode: str,
    access_token: str | None,
    ssh_private_key: str | None,
    verify_ssl: bool,
    linked_repo_id: str | None,
    bearer_session_token: str | None,
    suite: TestSuite | None,
) -> dict:
    if linked_repo_id:
        repo = db.get(Repository, linked_repo_id.strip())
        if not repo:
            return _response(
                success=False,
                source="none",
                default_branch="main",
                branch_names=[],
                error_message="关联的业务仓库不存在",
            )
        try:
            items = list_repository_branches(repo)
        except Exception as exc:
            return _response(
                success=False,
                source="linked_repo",
                default_branch=repo.default_branch or "main",
                branch_names=[],
                error_message=f"无法列举分支: {exc}",
            )
        default = (repo.default_branch or "main").strip() or "main"
        return _response(
            success=True,
            source="linked_repo",
            default_branch=default,
            branch_names=items,
        )

    resolved = (clone_url or "").strip()
    token = (access_token or "").strip() or None
    ssh_key = (ssh_private_key or "").strip() or None

    if not resolved:
        return _response(
            success=False,
            source="none",
            default_branch="main",
            branch_names=[],
            error_message="请先填写仓库地址",
        )

    if is_local_clone_url(resolved):
        try:
            items, default = await _local_branches_async(resolved)
        except Exception as exc:
            return _response(
                success=False,
                source="local_git",
                default_branch="main",
                branch_names=[],
                error_message=str(exc),
            )
        return _response(success=True, source="local_git", default_branch=default, branch_names=items)

    auth_method = _auth_method_from_mode(credential_mode)
    creds = resolve_git_clone_credentials(
        db,
        resolved,
        explicit_auth_method=auth_method,
        explicit_token=token,
        explicit_ssh_key=ssh_key,
        stored_auth_method=getattr(suite, "git_auth_method", None) if suite else None,
        stored_token=getattr(suite, "access_token", None) if suite else None,
        stored_ssh_key=getattr(suite, "ssh_private_key", None) if suite else None,
        git_reuse_repository_id=None,
        bearer_session_token=bearer_session_token,
    )
    meta = parse_clone_url_meta(resolved, None)
    api_token = creds.access_token if creds.auth_method == "token" else token

    if meta and meta.provider == "github" and resolved.startswith(("http://", "https://")):
        hit = await _try_github_api_async(meta, api_token)
        if hit:
            return hit

    if meta and meta.provider == "gitlab" and resolved.startswith(("http://", "https://")):
        hit = await _try_gitlab_api_async(meta, api_token, clone_url=resolved, verify_ssl=verify_ssl)
        if hit:
            return hit

    return await _detect_via_ls_remote_async(resolved, creds, verify_ssl=verify_ssl)


async def detect_repository_branches_async(
    db: Session,
    *,
    clone_url: str | None,
    credential_mode: str = "auto",
    access_token: str | None = None,
    ssh_private_key: str | None = None,
    verify_ssl: bool = True,
    linked_repo_id: str | None = None,
    bearer_session_token: str | None = None,
    suite: TestSuite | None = None,
) -> dict:
    try:
        return await asyncio.wait_for(
            _detect_impl_async(
                db,
                clone_url=(clone_url or "").strip(),
                credential_mode=credential_mode,
                access_token=access_token,
                ssh_private_key=ssh_private_key,
                verify_ssl=verify_ssl,
                linked_repo_id=linked_repo_id,
                bearer_session_token=bearer_session_token,
                suite=suite,
            ),
            timeout=_DETECT_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        return _response(
            success=False,
            source="none",
            default_branch="main",
            branch_names=[],
            error_message="分支探测超时（8s），请检查地址与网络或稍后重试",
        )


def detect_repository_branches(
    db: Session,
    *,
    clone_url: str | None,
    credential_mode: str = "auto",
    access_token: str | None = None,
    ssh_private_key: str | None = None,
    verify_ssl: bool = True,
    linked_repo_id: str | None = None,
    bearer_session_token: str | None = None,
    suite: TestSuite | None = None,
) -> dict:
    """同步包装（供 legacy 调用方）。"""
    return asyncio.run(
        detect_repository_branches_async(
            db,
            clone_url=clone_url,
            credential_mode=credential_mode,
            access_token=access_token,
            ssh_private_key=ssh_private_key,
            verify_ssl=verify_ssl,
            linked_repo_id=linked_repo_id,
            bearer_session_token=bearer_session_token,
            suite=suite,
        )
    )


def list_suite_source_branches(
    db: Session,
    *,
    git_url: str | None,
    git_reuse_repository_id: str | None,
    git_auth_method: str | None,
    access_token: str | None,
    ssh_private_key: str | None,
    bearer_session_token: str | None,
    suite: TestSuite | None = None,
    skip_ssl_verify: bool | None = None,
) -> dict:
    mode = "auto"
    if (git_auth_method or "").lower() == "token":
        mode = "token"
    elif (git_auth_method or "").lower() == "ssh":
        mode = "ssh"

    result = detect_repository_branches(
        db,
        clone_url=(git_url or "").strip() or None,
        credential_mode=mode,
        access_token=access_token,
        ssh_private_key=ssh_private_key,
        verify_ssl=not bool(skip_ssl_verify),
        linked_repo_id=git_reuse_repository_id,
        bearer_session_token=bearer_session_token,
        suite=suite,
    )
    names = [b["name"] for b in result.get("branches") or []]
    return {
        "ok": bool(result.get("success")),
        "items": names,
        "default_branch": result.get("default_branch") or "main",
        "message": result.get("error_message") or "",
        "source": result.get("source"),
    }