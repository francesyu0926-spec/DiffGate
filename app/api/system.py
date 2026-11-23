from fastapi import APIRouter

from app.config import get_settings
from sqlalchemy import text

from app.db.session import SessionLocal

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

    return {
        "api_online": True,
        "db_online": db_online,
        "ast_engine": "online" if ast_online else "offline",
        "redis_online": redis_online,
        "use_redis": settings.use_redis,
        "worker_mode": worker_mode,
        "worker_online": worker_online,
        "webhook_github": "POST /api/v1/webhooks/github",
        "webhook_gitlab": "POST /api/v1/webhooks/gitlab",
    }