from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.auth import LoginBody
from app.config import get_settings
from app.db.session import SessionLocal, get_db
from app.services.auth_login import perform_login
from app.services.rbac import resolve_actor

router = APIRouter(prefix="/system", tags=["system"])


def _db_online() -> bool:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        db.close()


def _ast_engine_online() -> bool:
    try:
        from app.engine.reverse_trace import ReverseTraceEngine

        ReverseTraceEngine()
        return True
    except Exception:
        return False


@router.post("/local-dev-login")
def local_dev_login(request: Request, db: Session = Depends(get_db)) -> dict:
    """本地调试登录（与 /auth/login 等价；旧进程未热载 auth 路由时可用）。"""
    body = LoginBody(provider="local", dev_local=True)
    return perform_login(db, request, body)


@router.get("/whoami")
def whoami(
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
    return {
        "username": actor.username,
        "role": actor.role,
        "role_label": actor.role_label,
        "email": actor.email or None,
        "can_manual_override": actor.can_override,
        "override_roles": get_settings().override_roles,
    }


@router.get("/status")
def system_status() -> dict:
    settings = get_settings()
    redis_online = False
    if settings.use_redis:
        try:
            import redis

            redis_online = bool(redis.from_url(settings.redis_url, decode_responses=True).ping())
        except Exception:
            redis_online = False

    if settings.use_background_tasks:
        worker_mode = "background"
    elif settings.celery_always_eager:
        worker_mode = "eager"
    else:
        worker_mode = "celery"
    worker_online = 4 if worker_mode == "celery" and redis_online else 1

    db_online = _db_online()
    ast_online = _ast_engine_online() if db_online else False

    base = (settings.webhook_public_base_url or "").rstrip("/")
    github_path = "/api/v1/webhooks/github"
    gitlab_path = "/api/v1/webhooks/gitlab"
    return {
        "api_online": True,
        "db_online": db_online,
        "ast_engine": "online" if ast_online else "offline",
        "redis_online": redis_online,
        "use_redis": settings.use_redis,
        "worker_mode": worker_mode,
        "worker_online": worker_online,
        "webhook_github": f"POST {github_path}",
        "webhook_gitlab": f"POST {gitlab_path}",
        "webhook_public_base_url": base or None,
        "webhook_github_url": f"{base}{github_path}" if base else None,
        "webhook_gitlab_url": f"{base}{gitlab_path}" if base else None,
        "webhook_secret_github_configured": bool(settings.webhook_secret_github),
        "webhook_secret_gitlab_configured": bool(settings.webhook_secret_gitlab),
    }