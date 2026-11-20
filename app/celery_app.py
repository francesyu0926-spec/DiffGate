from celery import Celery

from app.config import get_settings

settings = get_settings()

celery = Celery(
    "diffgate",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.analysis"],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
)

if settings.celery_always_eager:
    celery.conf.task_always_eager = True
    celery.conf.task_store_eager_result = True