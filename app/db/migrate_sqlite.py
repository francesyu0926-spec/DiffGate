"""SQLite 轻量补列（无 Alembic 时本地开发用）。"""

from sqlalchemy import inspect, text

from app.db.session import engine


def ensure_analysis_job_columns() -> None:
    if not inspect(engine).has_table("analysis_jobs"):
        return
    cols = {c["name"] for c in inspect(engine).get_columns("analysis_jobs")}
    if "gate_result" not in cols:
        col_type = "JSON" if engine.dialect.name == "sqlite" else "JSON"
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE analysis_jobs ADD COLUMN gate_result {col_type}"))


def ensure_repository_columns() -> None:
    if engine.dialect.name != "sqlite":
        return
    cols = {c["name"] for c in inspect(engine).get_columns("repositories")}
    patches = {
        "coverage_threshold": "INTEGER DEFAULT 80",
        "ast_method_count": "INTEGER DEFAULT 0",
        "ast_api_count": "INTEGER DEFAULT 0",
        "auth_method": "VARCHAR(16) DEFAULT 'none'",
        "access_token": "TEXT",
        "ssh_private_key": "TEXT",
        "scan_root": "VARCHAR(255) DEFAULT '.'",
        "test_suite_id": "VARCHAR(128)",
        "gate_path_rules": "JSON",
    }
    with engine.begin() as conn:
        for name, ddl in patches.items():
            if name not in cols:
                conn.execute(text(f"ALTER TABLE repositories ADD COLUMN {name} {ddl}"))


def ensure_analysis_job_extra_columns() -> None:
    if engine.dialect.name != "sqlite":
        return
    if not inspect(engine).has_table("analysis_jobs"):
        return
    cols = {c["name"] for c in inspect(engine).get_columns("analysis_jobs")}
    if "job_metadata" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE analysis_jobs ADD COLUMN job_metadata JSON"))