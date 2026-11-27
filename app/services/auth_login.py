"""登录编排（PAT / 本地调试），供 auth 与 system 路由共用。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from fastapi import HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import DiffGateUser
from app.services.auth_session import create_session, user_to_actor_payload
from app.services.git_platform_auth import (
    GitAuthError,
    apply_global_role_from_grants,
    sync_repo_grants,
    verify_github_token,
    verify_gitlab_token,
)
from app.services.rbac import ROLE_LABELS, actor_from_user


class LoginRequest(Protocol):
    provider: str
    access_token: str | None
    gitlab_base_url: str | None
    dev_local: bool


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_local_request(request: Request) -> bool:
    if request.client and request.client.host in ("127.0.0.1", "::1", "localhost"):
        return True
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded in ("127.0.0.1", "::1", "localhost"):
        return True
    host = (request.headers.get("host") or "").split(":")[0].lower()
    return host in ("127.0.0.1", "localhost")


def perform_login(db: Session, request: Request, body: LoginRequest) -> dict[str, Any]:
    identity: dict[str, Any]
    if body.provider == "local":
        if not body.dev_local or not _is_local_request(request):
            raise HTTPException(status_code=400, detail="仅 localhost 调试时可使用本地体验登录")
        identity = {
            "provider": "local",
            "git_user_id": "local",
            "username": "local-dev",
            "display_name": "本地调试",
            "email": "dev@localhost",
            "avatar_url": None,
        }
    elif body.provider == "github":
        if not body.access_token or len(body.access_token.strip()) < 8:
            raise HTTPException(status_code=400, detail="请填写 GitHub Personal Access Token")
        try:
            identity = verify_github_token(body.access_token)
        except GitAuthError as e:
            raise HTTPException(
                status_code=401,
                detail="令牌验证失败，请检查是否复制完整，或点击下方链接重新生成",
            ) from e
    else:
        if not body.access_token or len(body.access_token.strip()) < 8:
            raise HTTPException(status_code=400, detail="请填写 GitLab Personal Access Token")
        try:
            identity = verify_gitlab_token(body.gitlab_base_url or "https://gitlab.com", body.access_token)
        except GitAuthError as e:
            raise HTTPException(
                status_code=401,
                detail="令牌验证失败，请检查是否复制完整，或点击下方链接重新生成",
            ) from e

    user_count = int(db.query(func.count(DiffGateUser.id)).scalar() or 0)
    user = (
        db.query(DiffGateUser)
        .filter(
            DiffGateUser.provider == identity["provider"],
            DiffGateUser.git_user_id == identity["git_user_id"],
        )
        .one_or_none()
    )
    if not user:
        user = DiffGateUser(
            id=str(uuid.uuid4()),
            provider=identity["provider"],
            git_user_id=identity["git_user_id"],
            username=identity["username"],
            display_name=identity["display_name"],
            email=identity.get("email") or "",
            avatar_url=identity.get("avatar_url"),
            global_role="admin" if user_count == 0 else "dev",
            role_locked=False,
        )
        db.add(user)
    else:
        user.username = identity["username"]
        user.display_name = identity["display_name"]
        if identity.get("email"):
            user.email = identity["email"]
        user.avatar_url = identity.get("avatar_url")
        if user_count == 0 and not user.role_locked:
            user.global_role = "admin"
    user.last_login_at = _utcnow()

    if body.provider != "local" and body.access_token:
        sync_repo_grants(
            db,
            user,
            provider=identity["provider"],
            token=body.access_token,
            gitlab_base_url=body.gitlab_base_url,
        )
        apply_global_role_from_grants(db, user)

    pat = (body.access_token or "").strip() or None
    gl_base = None
    if body.provider == "gitlab":
        gl_base = identity.get("gitlab_base_url") or body.gitlab_base_url
    token = create_session(
        db,
        user,
        platform_access_token=pat if body.provider not in ("local",) else None,
        gitlab_base_url=gl_base,
        platform_provider=identity["provider"] if body.provider != "local" else None,
    )
    db.commit()
    actor = actor_from_user(user)
    payload = user_to_actor_payload(user, can_override=actor.can_override)
    payload["role_label"] = ROLE_LABELS.get(user.global_role, user.global_role)
    payload["session_token"] = token
    payload["authenticated"] = True
    payload["needs_password_setup"] = not bool(user.password_hash)
    return payload