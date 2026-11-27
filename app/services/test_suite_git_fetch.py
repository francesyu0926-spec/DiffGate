"""用例集 Git 浅克隆（统一凭据链）。"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from git import GitCommandError, Repo

from app.services.git_clone import clone_repository, inject_access_token
from app.services.git_credential_chain import GitCredentialResolution, auth_failure_message
from app.services.gitlab_private import gitlab_api_base, resolve_git_ssl_verify
from app.services.gitlab_user_errors import map_git_failure_message
from app.services.repo_detect_parse import parse_clone_url_meta


class ShallowCloneError(Exception):
    def __init__(self, message: str, credential_source: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.credential_source = credential_source


@dataclass
class _CloneAuth:
    id: str
    clone_url: str
    provider: str
    auth_method: str
    access_token: str | None = None
    ssh_private_key: str | None = None


def shallow_clone_with_credentials(
    git_url: str,
    branch: str | None,
    creds: GitCredentialResolution,
    *,
    skip_ssl_verify: bool | None = None,
) -> Path:
    meta = parse_clone_url_meta(git_url, None)
    api_base = gitlab_api_base(meta, "https://gitlab.com") if meta else git_url
    ssl_verify = resolve_git_ssl_verify(git_url, skip_ssl_verify)

    if meta and meta.transport == "ssh" and creds.auth_method != "ssh":
        if not creds.has_credentials:
            raise ShallowCloneError(
                "SSH 仓库地址需配置 SSH 私钥，或改用 HTTPS 地址并配置 Access Token",
                creds.credential_source,
            )

    clone_target = git_url
    method = creds.auth_method
    if method == "token" and creds.access_token:
        clone_target = inject_access_token(git_url, creds.access_token, creds.provider)
    elif method == "none":
        method = "none"

    pseudo = _CloneAuth(
        id=f"fetch-{uuid.uuid4().hex[:8]}",
        clone_url=clone_target if method == "token" else git_url,
        provider=creds.provider,
        auth_method=method if creds.has_credentials else "none",
        access_token=creds.access_token,
        ssh_private_key=creds.ssh_private_key,
    )

    dest = Path(tempfile.mkdtemp(prefix="dg-suite-fetch-"))
    br = (branch or "main").strip() or None
    kwargs: dict = {"depth": 1}
    if br:
        kwargs["branch"] = br

    env = os.environ.copy()
    if not ssl_verify:
        env["GIT_SSL_NO_VERIFY"] = "true"

    prev_ssl = os.environ.get("GIT_SSL_NO_VERIFY")
    if not ssl_verify:
        os.environ["GIT_SSL_NO_VERIFY"] = "true"
    try:
        if pseudo.auth_method == "ssh" and pseudo.ssh_private_key:
            clone_repository(pseudo, dest, **kwargs)  # type: ignore[arg-type]
        else:
            Repo.clone_from(pseudo.clone_url, str(dest), env=env, **kwargs)
    except GitCommandError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        hint = str(exc.stderr or exc)
        if "401" in hint or "403" in hint or "authentication" in hint.lower():
            msg = auth_failure_message(creds)
        else:
            msg = map_git_failure_message(
                hint,
                base_url=api_base,
                branch=br,
                ssl_verify=ssl_verify,
            )
        raise ShallowCloneError(msg, creds.credential_source) from exc
    finally:
        if prev_ssl is None:
            os.environ.pop("GIT_SSL_NO_VERIFY", None)
        else:
            os.environ["GIT_SSL_NO_VERIFY"] = prev_ssl
    return dest