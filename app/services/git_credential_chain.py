"""Git 拉取凭据三级回退：独立配置 → 登录会话 PAT → 关联仓库 / 全局令牌。"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AuthSession, DiffGateUser, Repository, TestSuite
from app.services.auth_session import resolve_session_with_pat
from app.services.repo_detect_parse import CloneUrlMeta, parse_clone_url_meta


@dataclass
class GitCredentialResolution:
    auth_method: str
    provider: str
    clone_url: str
    access_token: str | None = None
    ssh_private_key: str | None = None
    credential_source: str = "anonymous"
    source_label: str = ""

    @property
    def has_credentials(self) -> bool:
        if self.auth_method == "token":
            return bool((self.access_token or "").strip())
        if self.auth_method == "ssh":
            return bool((self.ssh_private_key or "").strip())
        return False


def normalize_git_netloc(url: str | None) -> str | None:
    if not url:
        return None
    raw = url.strip()
    if not raw.startswith(("http://", "https://")):
        if "@" in raw and not raw.startswith("git@"):
            raw = f"https://{raw}"
        elif "/" in raw or ":" in raw:
            parsed_host = raw.split("/", 1)[0]
            raw = f"https://{parsed_host}"
        else:
            raw = f"https://{raw}"
    try:
        u = urlparse(raw)
    except Exception:
        return None
    host = (u.hostname or "").lower()
    if not host:
        return None
    port = u.port
    if port and not ((u.scheme == "http" and port == 80) or (u.scheme == "https" and port == 443)):
        return f"{host}:{port}"
    return host


def gitlab_instances_match(meta: CloneUrlMeta, user_gitlab_base: str | None) -> bool:
    user_net = normalize_git_netloc(user_gitlab_base or "https://gitlab.com")
    target_net = normalize_git_netloc(meta.base_url) if meta.base_url else (meta.host or "").lower()
    if not user_net or not target_net:
        return False
    return user_net == target_net


def session_matches_clone_url(
    sess: AuthSession,
    user: DiffGateUser,
    meta: CloneUrlMeta,
) -> bool:
    if meta.provider == "local":
        return False
    prov = (sess.platform_provider or user.provider or "").lower()
    if prov != meta.provider:
        return False
    if not (sess.platform_access_token or "").strip():
        return False
    if meta.provider == "github":
        return True
    if meta.provider == "gitlab":
        return gitlab_instances_match(meta, sess.gitlab_base_url)
    return False


def _resolution(
    *,
    auth_method: str,
    provider: str,
    clone_url: str,
    access_token: str | None = None,
    ssh_private_key: str | None = None,
    credential_source: str,
    source_label: str,
) -> GitCredentialResolution:
    return GitCredentialResolution(
        auth_method=auth_method,
        provider=provider,
        clone_url=clone_url,
        access_token=access_token,
        ssh_private_key=ssh_private_key,
        credential_source=credential_source,
        source_label=source_label,
    )


def credentials_from_repository(repo: Repository, clone_url: str, provider: str) -> GitCredentialResolution | None:
    method = (repo.auth_method or "none").lower()
    if method == "ssh" and (repo.ssh_private_key or "").strip():
        return _resolution(
            auth_method="ssh",
            provider=repo.provider or provider,
            clone_url=repo.clone_url or clone_url,
            ssh_private_key=repo.ssh_private_key,
            credential_source="linked_repository",
            source_label=f"业务仓库 {repo.full_name}",
        )
    if method == "token" and (repo.access_token or "").strip():
        return _resolution(
            auth_method="token",
            provider=repo.provider or provider,
            clone_url=repo.clone_url or clone_url,
            access_token=repo.access_token,
            credential_source="linked_repository",
            source_label=f"业务仓库 {repo.full_name}",
        )
    return None


def resolve_git_clone_credentials(
    db: Session,
    clone_url: str,
    *,
    explicit_auth_method: str | None = "inherit",
    explicit_token: str | None = None,
    explicit_ssh_key: str | None = None,
    stored_auth_method: str | None = None,
    stored_token: str | None = None,
    stored_ssh_key: str | None = None,
    git_reuse_repository_id: str | None = None,
    bearer_session_token: str | None = None,
) -> GitCredentialResolution:
    meta = parse_clone_url_meta(clone_url, None)
    provider = (meta.provider if meta and meta.provider != "local" else None) or "gitlab"

    req_method = (explicit_auth_method or "inherit").lower()
    stored_method = (stored_auth_method or "inherit").lower()

    if req_method == "ssh":
        key = (explicit_ssh_key or "").strip()
        if key:
            return _resolution(
                auth_method="ssh",
                provider=provider,
                clone_url=clone_url,
                ssh_private_key=key,
                credential_source="explicit",
                source_label="用例集/表单 SSH 私钥",
            )
    elif req_method == "token":
        tok = (explicit_token or "").strip()
        if tok:
            return _resolution(
                auth_method="token",
                provider=provider,
                clone_url=clone_url,
                access_token=tok,
                credential_source="explicit",
                source_label="用例集/表单 Access Token",
            )

    if stored_method == "ssh" and (stored_ssh_key or "").strip():
        return _resolution(
            auth_method="ssh",
            provider=provider,
            clone_url=clone_url,
            ssh_private_key=stored_ssh_key,
            credential_source="explicit",
            source_label="用例集已保存 SSH 私钥",
        )
    if stored_method == "token" and (stored_token or "").strip():
        return _resolution(
            auth_method="token",
            provider=provider,
            clone_url=clone_url,
            access_token=stored_token,
            credential_source="explicit",
            source_label="用例集已保存 Access Token",
        )

    if meta and meta.transport == "ssh" and req_method == "inherit" and stored_method == "inherit":
        pass

    if bearer_session_token and meta:
        pair = resolve_session_with_pat(db, bearer_session_token)
        if pair:
            sess, user = pair
            if session_matches_clone_url(sess, user, meta):
                return _resolution(
                    auth_method="token",
                    provider=provider,
                    clone_url=clone_url,
                    access_token=sess.platform_access_token,
                    credential_source="user_session",
                    source_label=f"当前登录用户 {user.username}",
                )

    if git_reuse_repository_id:
        repo = db.get(Repository, git_reuse_repository_id.strip())
        if repo:
            hit = credentials_from_repository(repo, clone_url, provider)
            if hit:
                return hit

    settings = get_settings()
    if provider == "gitlab" and (settings.gitlab_token or "").strip():
        return _resolution(
            auth_method="token",
            provider=provider,
            clone_url=clone_url,
            access_token=settings.gitlab_token.strip(),
            credential_source="global",
            source_label="系统 gitlab_token",
        )
    if provider == "github" and (settings.github_token or "").strip():
        return _resolution(
            auth_method="token",
            provider=provider,
            clone_url=clone_url,
            access_token=settings.github_token.strip(),
            credential_source="global",
            source_label="系统 github_token",
        )

    return _resolution(
        auth_method="none",
        provider=provider,
        clone_url=clone_url,
        credential_source="anonymous",
        source_label="无认证（仅适用于公开仓库）",
    )


def resolve_for_test_suite(
    db: Session,
    *,
    clone_url: str,
    suite: TestSuite | None,
    git_auth_method: str | None,
    access_token: str | None,
    ssh_private_key: str | None,
    git_reuse_repository_id: str | None,
    bearer_session_token: str | None,
) -> GitCredentialResolution:
    stored_method = getattr(suite, "git_auth_method", None) if suite else None
    stored_token = getattr(suite, "access_token", None) if suite else None
    stored_ssh = getattr(suite, "ssh_private_key", None) if suite else None
    reuse_id = git_reuse_repository_id or (suite.git_reuse_repository_id if suite else None)
    return resolve_git_clone_credentials(
        db,
        clone_url,
        explicit_auth_method=git_auth_method,
        explicit_token=access_token,
        explicit_ssh_key=ssh_private_key,
        stored_auth_method=stored_method,
        stored_token=stored_token,
        stored_ssh_key=stored_ssh,
        git_reuse_repository_id=reuse_id,
        bearer_session_token=bearer_session_token,
    )


AUTH_FAILURE_GUIDE = (
    "私有仓库认证失败（401/403）。请依次检查："
    "① 用例集「独立凭证」中的 Access Token 或 SSH；"
    "② 使用与仓库 GitLab 实例同域账号通过 PAT 登录 DiffGate；"
    "③ 关联业务仓库已保存凭据，或由管理员配置全局 gitlab_token / github_token。"
)


def auth_failure_message(resolution: GitCredentialResolution | None = None) -> str:
    if resolution and resolution.credential_source != "anonymous":
        return f"{AUTH_FAILURE_GUIDE}（最近使用：{resolution.source_label}）"
    return AUTH_FAILURE_GUIDE