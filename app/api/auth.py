"""零配置 PAT 登录与会话。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import DiffGateUser
from app.db.session import get_db
from app.config import get_settings
from app.services.auth_login import perform_login
from app.services.auth_session import revoke_session
from app.services.rbac import ROLE_LABELS, actor_can_override, resolve_actor

router = APIRouter(prefix="/auth", tags=["auth"])

Provider = Literal["github", "gitlab", "local"]


class LoginBody(BaseModel):
    provider: Provider = "github"
    access_token: str | None = Field(default=None, max_length=4096)
    gitlab_base_url: str | None = Field(default="https://gitlab.com", max_length=512)
    dev_local: bool = False


class PasswordLoginBody(BaseModel):
    login: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=256)


class SetPasswordBody(BaseModel):
    password: str = Field(..., min_length=8, max_length=256)
    password_confirm: str = Field(..., min_length=8, max_length=256)


class MemberRolePatch(BaseModel):
    role: Literal["dev", "qa", "admin", "pm"]
    role_locked: bool = True


@router.get("/token-wizard")
def token_wizard(gitlab_base_url: str = "https://gitlab.com") -> dict:
    base = gitlab_base_url.rstrip("/")
    return {
        "github": {
            "label": "GitHub",
            "create_url": (
                "https://github.com/settings/tokens/new"
                "?description=DiffGate&scopes=read:user,user:email,repo"
            ),
            "scopes_hint": "read:user、user:email、repo",
            "wizard_link_text": (
                "没有 Token？点此 5 秒一键生成（已自动预填名称与最小只读权限）↗"
            ),
        },
        "gitlab": {
            "label": "GitLab",
            "create_url": f"{base}/-/user_settings/personal_access_tokens",
            "scopes_hint": "read_user、read_api",
            "wizard_link_text": (
                "没有 Token？点此前往 GitLab 个人令牌生成（勾选 read_user 与 read_api）↗"
            ),
        },
    }


@router.post("/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)) -> dict:
    return perform_login(db, request, body)


@router.post("/login-password")
def login_password(body: PasswordLoginBody, db: Session = Depends(get_db)) -> dict:
    from app.services.auth_password import login_with_password

    return login_with_password(db, body.login, body.password)


@router.post("/set-password")
def set_password(
    body: SetPasswordBody,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
) -> dict:
    from app.services.auth_session import resolve_user_by_token
    from app.services.auth_password import set_user_password

    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    user = resolve_user_by_token(db, token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    set_user_password(db, user, body.password, body.password_confirm)
    return {"ok": True}


@router.post("/logout")
def logout(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> dict:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token:
        revoke_session(db, token)
        db.commit()
    return {"ok": True}


@router.get("/session")
def auth_session(
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
    x_diffgate_user: str | None = Header(None, alias="X-DiffGate-User"),
    x_diffgate_role: str | None = Header(None, alias="X-DiffGate-Role"),
    x_diffgate_email: str | None = Header(None, alias="X-DiffGate-Email"),
) -> dict:
    actor = resolve_actor(
        db,
        authorization=authorization,
        x_diffgate_user=x_diffgate_user,
        x_diffgate_role=x_diffgate_role,
        x_diffgate_email=x_diffgate_email,
    )
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    user = None
    if token:
        from app.services.auth_session import resolve_user_by_token

        user = resolve_user_by_token(db, token)
    return {
        "authenticated": bool(user),
        "username": actor.username,
        "role": actor.role,
        "role_label": actor.role_label,
        "email": actor.email or None,
        "can_manual_override": actor.can_override,
        "display_name": user.display_name if user else actor.username,
        "avatar_url": user.avatar_url if user else None,
        "user_id": user.id if user else None,
        "override_roles": get_settings().override_roles,
    }


@router.get("/members")
def list_members(
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
    x_diffgate_user: str | None = Header(None, alias="X-DiffGate-User"),
    x_diffgate_role: str | None = Header(None, alias="X-DiffGate-Role"),
    x_diffgate_email: str | None = Header(None, alias="X-DiffGate-Email"),
) -> dict:
    actor = resolve_actor(
        db,
        authorization=authorization,
        x_diffgate_user=x_diffgate_user,
        x_diffgate_role=x_diffgate_role,
        x_diffgate_email=x_diffgate_email,
    )
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看成员列表")
    rows = db.query(DiffGateUser).order_by(DiffGateUser.last_login_at.desc()).all()
    return {
        "items": [
            {
                "user_id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "email": u.email or None,
                "avatar_url": u.avatar_url,
                "role": u.global_role,
                "role_label": ROLE_LABELS.get(u.global_role, u.global_role),
                "role_locked": u.role_locked,
                "provider": u.provider,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            }
            for u in rows
        ]
    }


@router.patch("/members/{user_id}")
def patch_member_role(
    user_id: str,
    body: MemberRolePatch,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
    x_diffgate_user: str | None = Header(None, alias="X-DiffGate-User"),
    x_diffgate_role: str | None = Header(None, alias="X-DiffGate-Role"),
    x_diffgate_email: str | None = Header(None, alias="X-DiffGate-Email"),
) -> dict:
    actor = resolve_actor(
        db,
        authorization=authorization,
        x_diffgate_user=x_diffgate_user,
        x_diffgate_role=x_diffgate_role,
        x_diffgate_email=x_diffgate_email,
    )
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可调整成员角色")
    user = db.query(DiffGateUser).filter(DiffGateUser.id == user_id).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.global_role = body.role
    user.role_locked = body.role_locked
    db.commit()
    return {
        "user_id": user.id,
        "role": user.global_role,
        "role_label": ROLE_LABELS.get(user.global_role, user.global_role),
        "role_locked": user.role_locked,
        "can_manual_override": actor_can_override(user.global_role),
    }