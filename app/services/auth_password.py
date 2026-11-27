"""DiffGate 独立登录密码（PBKDF2，无额外依赖）。"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import DiffGateUser
from app.services.auth_session import create_session, user_to_actor_payload
from app.services.rbac import ROLE_LABELS, actor_from_user


def hash_password(plain: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(plain: str, stored: str | None) -> bool:
    if not stored or not plain:
        return False
    try:
        algo, salt, digest_hex = stored.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt.encode("utf-8"), 120_000)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except ValueError:
        return False


def login_with_password(db: Session, login: str, password: str) -> dict:
    key = login.strip().lower()
    if not key or not password:
        raise HTTPException(status_code=400, detail="请输入账号与密码")
    user = (
        db.query(DiffGateUser)
        .filter(
            or_(
                DiffGateUser.username == login.strip(),
                DiffGateUser.email == key,
            )
        )
        .one_or_none()
    )
    if not user:
        raise HTTPException(
            status_code=401,
            detail="该账号尚未绑定 DiffGate，请先通过「Git 令牌首次登录」完成初始化",
        )
    if not user.password_hash:
        raise HTTPException(
            status_code=401,
            detail="您尚未设置独立登录密码，请使用「Git 令牌登录」并在个人中心设置密码",
        )
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误，请重试")
    from datetime import datetime, timezone

    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    token = create_session(db, user)
    db.commit()
    actor = actor_from_user(user)
    payload = user_to_actor_payload(user, can_override=actor.can_override)
    payload["role_label"] = ROLE_LABELS.get(user.global_role, user.global_role)
    payload["session_token"] = token
    payload["authenticated"] = True
    payload["needs_password_setup"] = False
    return payload


def set_user_password(db: Session, user: DiffGateUser, password: str, confirm: str) -> None:
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    if password != confirm:
        raise HTTPException(status_code=400, detail="两次输入的密码不一致")
    user.password_hash = hash_password(password)
    db.commit()