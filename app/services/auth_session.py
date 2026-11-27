"""Bearer 会话：创建、解析、过期。"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import AuthSession, DiffGateUser


SESSION_TTL_DAYS = 7


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_session(
    db: Session,
    user: DiffGateUser,
    *,
    platform_access_token: str | None = None,
    gitlab_base_url: str | None = None,
    platform_provider: str | None = None,
) -> str:
    token = secrets.token_urlsafe(32)
    sess = AuthSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token=token,
        expires_at=_utcnow() + timedelta(days=SESSION_TTL_DAYS),
        platform_access_token=(platform_access_token or "").strip() or None,
        gitlab_base_url=(gitlab_base_url or "").strip().rstrip("/") or None,
        platform_provider=(platform_provider or "").strip().lower() or None,
    )
    db.add(sess)
    db.flush()
    return token


def bearer_token_from_header(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def resolve_session_with_pat(db: Session, bearer: str) -> tuple[AuthSession, DiffGateUser] | None:
    token = (bearer or "").strip()
    if not token or len(token) < 16:
        return None
    row = db.query(AuthSession).filter(AuthSession.token == token).one_or_none()
    if not row or row.expires_at < _utcnow():
        if row:
            db.delete(row)
            db.flush()
        return None
    user = db.query(DiffGateUser).filter(DiffGateUser.id == row.user_id).one_or_none()
    if not user:
        return None
    return row, user


def revoke_session(db: Session, token: str) -> None:
    row = db.query(AuthSession).filter(AuthSession.token == token).one_or_none()
    if row:
        db.delete(row)


def resolve_user_by_token(db: Session, token: str) -> DiffGateUser | None:
    if not token or len(token) < 16:
        return None
    row = db.query(AuthSession).filter(AuthSession.token == token).one_or_none()
    if not row or row.expires_at < _utcnow():
        if row:
            db.delete(row)
            db.flush()
        return None
    return db.query(DiffGateUser).filter(DiffGateUser.id == row.user_id).one_or_none()


def user_to_actor_payload(user: DiffGateUser, *, can_override: bool) -> dict:
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.global_role,
        "email": user.email or None,
        "avatar_url": user.avatar_url,
        "can_manual_override": can_override,
        "provider": user.provider,
    }