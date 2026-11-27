"""GitHub / GitLab PAT 校验与仓库成员权限拉取（登录时一次性，不落库 PAT）。"""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.db.models import DiffGateUser, Repository, UserRepoGrant


class GitAuthError(Exception):
    pass


def verify_github_token(token: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get("https://api.github.com/user", headers=headers)
    except httpx.RequestError as e:
        raise GitAuthError(f"无法连接 GitHub：{e}") from e
    if r.status_code == 401:
        raise GitAuthError("GitHub Token 无效或已过期")
    if r.status_code >= 400:
        raise GitAuthError(f"GitHub 核验失败（HTTP {r.status_code}）")
    data = r.json()
    return {
        "provider": "github",
        "git_user_id": str(data.get("id", "")),
        "username": str(data.get("login") or "").strip(),
        "display_name": str(data.get("name") or data.get("login") or "").strip(),
        "email": str(data.get("email") or "").strip().lower(),
        "avatar_url": data.get("avatar_url"),
    }


def verify_gitlab_token(base_url: str, token: str) -> dict[str, Any]:
    base = (base_url or "https://gitlab.com").rstrip("/")
    headers = {"PRIVATE-TOKEN": token.strip()}
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(f"{base}/api/v4/user", headers=headers)
    except httpx.RequestError as e:
        raise GitAuthError(f"无法连接 GitLab：{e}") from e
    if r.status_code == 401:
        raise GitAuthError("GitLab Token 无效或已过期")
    if r.status_code >= 400:
        raise GitAuthError(f"GitLab 核验失败（HTTP {r.status_code}）")
    data = r.json()
    return {
        "provider": "gitlab",
        "git_user_id": str(data.get("id", "")),
        "username": str(data.get("username") or "").strip(),
        "display_name": str(data.get("name") or data.get("username") or "").strip(),
        "email": str(data.get("email") or data.get("public_email") or "").strip().lower(),
        "avatar_url": data.get("avatar_url"),
        "gitlab_base_url": base,
    }


def _github_repo_permission(
    client: httpx.Client, headers: dict[str, str], full_name: str, username: str
) -> str | None:
    owner, _, repo = full_name.partition("/")
    if not owner or not repo:
        return None
    path = f"/repos/{owner}/{repo}/collaborators/{urllib.parse.quote(username)}/permission"
    r = client.get(f"https://api.github.com{path}", headers=headers)
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        return None
    perm = str(r.json().get("permission") or "").lower()
    return perm or None


def _gitlab_repo_access(
    client: httpx.Client, base: str, headers: dict[str, str], full_name: str, git_user_id: str
) -> str | None:
    enc = urllib.parse.quote(full_name, safe="")
    r = client.get(f"{base}/api/v4/projects/{enc}", headers=headers)
    if r.status_code >= 400:
        r = client.get(
            f"{base}/api/v4/projects",
            headers=headers,
            params={"search": full_name.split("/")[-1], "membership": True},
        )
        if r.status_code >= 400:
            return None
        projects = r.json()
        project = next((p for p in projects if p.get("path_with_namespace") == full_name), None)
        if not project:
            return None
        project_id = project["id"]
    else:
        project_id = r.json().get("id")
    if not project_id:
        return None
    r = client.get(
        f"{base}/api/v4/projects/{project_id}/members/all/{git_user_id}",
        headers=headers,
    )
    if r.status_code >= 400:
        return None
    level = int(r.json().get("access_level") or 0)
    if level >= 50:
        return "owner"
    if level >= 40:
        return "maintainer"
    if level >= 30:
        return "developer"
    if level >= 20:
        return "reporter"
    return "guest"


def _map_git_access_to_diffgate(access: str | None) -> tuple[str, str]:
    a = (access or "").lower()
    if a in ("admin", "owner", "maintainer", "maintain"):
        return a or "maintainer", "admin"
    if a in ("developer", "write", "reporter", "triage", "read"):
        return a or "developer", "dev"
    return "none", "dev"


def sync_repo_grants(
    db: Session,
    user: DiffGateUser,
    *,
    provider: str,
    token: str,
    gitlab_base_url: str | None = None,
) -> None:
    """遍历 DiffGate 已登记仓库，刷新用户在 Git 侧的权限映射。"""
    repos = db.query(Repository).filter(Repository.enabled.is_(True)).all()
    if not repos:
        return
    provider_l = provider.lower()
    headers: dict[str, str]
    if provider_l == "github":
        headers = {
            "Authorization": f"Bearer {token.strip()}",
            "Accept": "application/vnd.github+json",
        }
    else:
        base = (gitlab_base_url or "https://gitlab.com").rstrip("/")
        headers = {"PRIVATE-TOKEN": token.strip()}
    with httpx.Client(timeout=12.0) as client:
        for repo in repos[:40]:
            if (repo.provider or "").lower() != provider_l:
                continue
            access: str | None = None
            if provider_l == "github":
                access = _github_repo_permission(client, headers, repo.full_name, user.username)
            else:
                base = (gitlab_base_url or "https://gitlab.com").rstrip("/")
                access = _gitlab_repo_access(client, base, headers, repo.full_name, user.git_user_id)
            git_level, dg_role = _map_git_access_to_diffgate(access)
            existing = (
                db.query(UserRepoGrant)
                .filter(UserRepoGrant.user_id == user.id, UserRepoGrant.repo_id == repo.id)
                .one_or_none()
            )
            if existing:
                existing.git_access_level = git_level
                existing.diffgate_role = dg_role
            else:
                import uuid

                db.add(
                    UserRepoGrant(
                        id=str(uuid.uuid4()),
                        user_id=user.id,
                        repo_id=repo.id,
                        git_access_level=git_level,
                        diffgate_role=dg_role,
                    )
                )
    db.flush()


def apply_global_role_from_grants(db: Session, user: DiffGateUser) -> None:
    if user.role_locked:
        return
    grants = db.query(UserRepoGrant).filter(UserRepoGrant.user_id == user.id).all()
    if any(g.diffgate_role == "admin" for g in grants):
        if user.global_role == "dev":
            user.global_role = "admin"
    elif user.global_role not in ("admin", "qa", "pm"):
        user.global_role = "dev"