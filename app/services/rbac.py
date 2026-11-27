"""RBAC：人工豁免角色与提交人互斥（防自审）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.config import get_settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.db.models import DiffGateUser


ROLE_LABELS: dict[str, str] = {
    "dev": "研发",
    "qa": "测试 / QA",
    "pm": "项目负责人",
    "admin": "管理员",
    "owner": "负责人",
}

OVERRIDE_HINTS: dict[str, str] = {
    "insufficient_role": (
        "当前角色为「研发」，仅 QA 或项目负责人可执行豁免。"
        "可复制链接发给 QA 审批。"
    ),
    "self_submit": (
        "触发「提交人与审批人互斥」规则，请联系其他 QA / 负责人进行豁免。"
    ),
    "path_blocked": "命中不可豁免路径规则（如支付核心），请联系管理员处理。",
    "not_block": "当前批次非 BLOCK 状态，无需豁免。",
}


@dataclass
class SessionActor:
    username: str
    role: str
    email: str = ""
    can_override: bool = False

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)


def _parse_roles(raw: str) -> set[str]:
    return {r.strip().lower() for r in raw.split(",") if r.strip()}


def actor_can_override(role: str) -> bool:
    allowed = _parse_roles(get_settings().override_roles)
    return role in allowed or role == "admin"


def actor_from_user(user: "DiffGateUser") -> SessionActor:
    role = (user.global_role or "dev").strip().lower()
    return SessionActor(
        username=user.username,
        role=role,
        email=user.email or "",
        can_override=actor_can_override(role),
    )


def resolve_actor(
    db: "Session | None",
    *,
    authorization: str | None = None,
    x_diffgate_user: str | None = None,
    x_diffgate_role: str | None = None,
    x_diffgate_email: str | None = None,
) -> SessionActor:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if db and token:
        from app.services.auth_session import resolve_user_by_token

        user = resolve_user_by_token(db, token)
        if user:
            return actor_from_user(user)
    return actor_from_headers(x_diffgate_user, x_diffgate_role, x_diffgate_email)


def actor_from_headers(
    x_diffgate_user: str | None,
    x_diffgate_role: str | None,
    x_diffgate_email: str | None = None,
) -> SessionActor:
    settings = get_settings()
    username = (x_diffgate_user or settings.default_actor_name or "developer").strip()[:100]
    role = (x_diffgate_role or settings.default_actor_role or "dev").strip().lower()[:32]
    email = (x_diffgate_email or "").strip().lower()[:255]
    return SessionActor(
        username=username,
        role=role,
        email=email,
        can_override=actor_can_override(role),
    )


def job_commit_identities(job) -> dict[str, str]:
    meta = getattr(job, "job_metadata", None) or {}
    username = str(
        meta.get("commit_author_username")
        or meta.get("committer")
        or meta.get("commit_author")
        or "",
    ).strip()
    email = str(meta.get("commit_author_email") or "").strip()
    return {
        "username": username.lower(),
        "email": email.lower(),
        "display": username or email or "—",
    }


def job_commit_author(job) -> str:
    return job_commit_identities(job)["username"]


def _is_self_submit(actor: SessionActor, job) -> bool:
    ident = job_commit_identities(job)
    author_u = ident["username"]
    author_e = ident["email"]
    if not author_u and not author_e:
        return False
    auditor_u = actor.username.strip().lower()
    auditor_e = actor.email.strip().lower()
    if author_u and auditor_u and author_u == auditor_u:
        return True
    if author_e and auditor_e and author_e == auditor_e:
        return True
    if author_u and auditor_u and auditor_u in author_u:
        return True
    return False


def allow_self_override(repo) -> bool:
    return bool(repo and getattr(repo, "allow_self_override", False))


def evaluate_override_eligibility(
    actor: SessionActor,
    *,
    job=None,
    repo=None,
    gate: str | None = None,
    allow_override_flag: bool | None = True,
) -> dict[str, Any]:
    """返回前端展示用豁免资格与文案（不含敏感字段）。"""
    gate_u = str(gate or "").upper()
    if gate_u and gate_u not in ("BLOCK",):
        return {
            "allowed": False,
            "reason": "not_block",
            "hint": OVERRIDE_HINTS["not_block"],
            "actor_role": actor.role,
            "actor_role_label": actor.role_label,
        }
    if allow_override_flag is False:
        return {
            "allowed": False,
            "reason": "path_blocked",
            "hint": OVERRIDE_HINTS["path_blocked"],
            "actor_role": actor.role,
            "actor_role_label": actor.role_label,
        }
    if not actor.can_override:
        return {
            "allowed": False,
            "reason": "insufficient_role",
            "hint": OVERRIDE_HINTS["insufficient_role"],
            "actor_role": actor.role,
            "actor_role_label": actor.role_label,
        }
    if job and _is_self_submit(actor, job) and not allow_self_override(repo):
        return {
            "allowed": False,
            "reason": "self_submit",
            "hint": OVERRIDE_HINTS["self_submit"],
            "actor_role": actor.role,
            "actor_role_label": actor.role_label,
            "commit_author": job_commit_identities(job).get("display"),
        }
    return {
        "allowed": True,
        "reason": None,
        "hint": None,
        "actor_role": actor.role,
        "actor_role_label": actor.role_label,
        "auditor_label": f"{actor.username} ({actor.role_label})",
    }


def require_override_permission(
    actor: SessionActor,
    *,
    job=None,
    repo=None,
) -> None:
    gr = dict(getattr(job, "gate_result", None) or {})
    ev = evaluate_override_eligibility(
        actor,
        job=job,
        repo=repo,
        gate=str(gr.get("gate") or ""),
        allow_override_flag=gr.get("allow_override", True) is not False,
    )
    if ev["allowed"]:
        return
    reason = ev.get("reason")
    if reason == "insufficient_role":
        raise PermissionError("仅 QA、项目负责人或管理员可执行人工豁免")
    if reason == "self_submit":
        raise PermissionError("提交人与审批人互斥：当前登录用户为本次 Commit 提交人，不得自行豁免")
    if reason == "path_blocked":
        raise PermissionError("当前批次命中不可豁免路径规则，请联系负责人处理")
    raise PermissionError(ev.get("hint") or "无豁免权限")