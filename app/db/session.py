from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.models import Base


def _prepare_sqlite(dsn: str) -> None:
    if not dsn.startswith("sqlite"):
        return
    url = make_url(dsn)
    if not url.database or url.database == ":memory:":
        return
    db_path = Path(url.database)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


_settings = get_settings()
_prepare_sqlite(_settings.mysql_dsn)
_connect_kwargs: dict = {"pool_pre_ping": True}
if _settings.mysql_dsn.startswith("sqlite"):
    _connect_kwargs["connect_args"] = {"check_same_thread": False}
engine = create_engine(_settings.mysql_dsn, **_connect_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    from app.db.migrate_sqlite import (
        ensure_analysis_job_columns,
        ensure_analysis_job_extra_columns,
        ensure_auth_session_columns,
        ensure_diffgate_user_columns,
        ensure_repository_columns,
        ensure_repository_slot_index,
        ensure_test_suite_columns,
    )

    ensure_repository_columns()
    ensure_repository_slot_index()
    ensure_analysis_job_columns()
    ensure_analysis_job_extra_columns()
    ensure_diffgate_user_columns()
    ensure_auth_session_columns()
    ensure_test_suite_columns()
    from app.services.test_suite_seed import seed_default_test_suites

    db = SessionLocal()
    try:
        seed_default_test_suites(db)
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()