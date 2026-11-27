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


def ensure_repository_slot_index() -> None:
    if engine.dialect.name != "sqlite":
        return
    if not inspect(engine).has_table("repositories"):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_repositories_clone_scan_type "
                "ON repositories (clone_url, scan_root, repo_type)"
            )
        )


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
        "high_risk_paths": "JSON",
        "low_risk_paths": "JSON",
        "high_risk_api_threshold": "INTEGER",
        "high_risk_symbol_threshold": "INTEGER",
        "allow_self_override": "INTEGER DEFAULT 0",
        "webhook_notify_url": "VARCHAR(512)",
        "notify_webhook_url": "VARCHAR(512)",
        "notify_policy": "VARCHAR(32) DEFAULT 'block_only'",
        "repo_type": "VARCHAR(20) DEFAULT 'backend'",
        "api_base_prefix": "VARCHAR(128) DEFAULT ''",
        "api_strip_prefix": "VARCHAR(128) DEFAULT ''",
        "linked_repo_ids": "JSON",
    }
    with engine.begin() as conn:
        for name, ddl in patches.items():
            if name not in cols:
                conn.execute(text(f"ALTER TABLE repositories ADD COLUMN {name} {ddl}"))


def ensure_auth_session_columns() -> None:
    if not inspect(engine).has_table("auth_sessions"):
        return
    cols = {c["name"] for c in inspect(engine).get_columns("auth_sessions")}
    patches = {
        "platform_provider": "VARCHAR(16)",
        "gitlab_base_url": "VARCHAR(512)",
        "platform_access_token": "TEXT",
    }
    with engine.begin() as conn:
        for name, ddl in patches.items():
            if name not in cols:
                conn.execute(text(f"ALTER TABLE auth_sessions ADD COLUMN {name} {ddl}"))


def ensure_diffgate_user_columns() -> None:
    if not inspect(engine).has_table("diffgate_users"):
        return
    cols = {c["name"] for c in inspect(engine).get_columns("diffgate_users")}
    if "password_hash" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE diffgate_users ADD COLUMN password_hash TEXT"))


def ensure_test_suite_columns() -> None:
    if not inspect(engine).has_table("test_suites"):
        return
    cols = {c["name"] for c in inspect(engine).get_columns("test_suites")}
    patches = {
        "source_type": "VARCHAR(16) DEFAULT 'manual'",
        "git_url": "VARCHAR(512)",
        "git_branch": "VARCHAR(128)",
        "case_path": "VARCHAR(255)",
        "framework": "VARCHAR(32)",
        "git_reuse_repository_id": "VARCHAR(36)",
        "trigger_webhook_url": "VARCHAR(512)",
        "git_auth_method": "VARCHAR(16) DEFAULT 'inherit'",
        "access_token": "TEXT",
        "ssh_private_key": "TEXT",
        "skip_ssl_verify": "INTEGER DEFAULT 0",
        "indexed_api_count": "INTEGER DEFAULT 0",
        "case_count": "INTEGER DEFAULT 0",
        "last_synced_at": "DATETIME",
    }
    with engine.begin() as conn:
        for name, ddl in patches.items():
            if name not in cols:
                conn.execute(text(f"ALTER TABLE test_suites ADD COLUMN {name} {ddl}"))


def ensure_analysis_job_extra_columns() -> None:
    if engine.dialect.name != "sqlite":
        return
    if not inspect(engine).has_table("analysis_jobs"):
        return
    cols = {c["name"] for c in inspect(engine).get_columns("analysis_jobs")}
    if "job_metadata" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE analysis_jobs ADD COLUMN job_metadata JSON"))