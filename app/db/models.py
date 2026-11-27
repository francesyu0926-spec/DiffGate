from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TestSuite(Base):
    """平台可关联的精准回归 / API 用例集目录。"""

    __tablename__ = "test_suites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # git | webhook | manual
    source_type: Mapped[str] = mapped_column(String(16), default="manual")
    git_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    git_branch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    case_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    framework: Mapped[str | None] = mapped_column(String(32), nullable=True)
    git_reuse_repository_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    git_auth_method: Mapped[str] = mapped_column(String(16), default="inherit")
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_private_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_ssl_verify: Mapped[bool] = mapped_column(Boolean, default=False)
    trigger_webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    indexed_api_count: Mapped[int] = mapped_column(Integer, default=0)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class IndexedTestCase(Base):
    """用例集内单条可执行用例（case_uid 唯一）。"""

    __tablename__ = "indexed_test_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    suite_id: Mapped[str] = mapped_column(String(36), index=True)
    case_uid: Mapped[str] = mapped_column(String(512), index=True)
    title: Mapped[str] = mapped_column(String(255))
    run_selector: Mapped[str] = mapped_column(String(512))
    source_framework: Mapped[str] = mapped_column(String(32), default="yaml")
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class IndexedCaseApiBinding(Base):
    """一条用例可绑定多个 HTTP 契约（多步骤场景）。"""

    __tablename__ = "indexed_case_api_bindings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    http_method: Mapped[str] = mapped_column(String(16))
    raw_route: Mapped[str | None] = mapped_column(String(512), nullable=True)
    normalized_route: Mapped[str] = mapped_column(String(512), index=True)
    contract_key: Mapped[str] = mapped_column(String(512), index=True)


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(32))
    clone_url: Mapped[str] = mapped_column(String(512))
    default_branch: Mapped[str] = mapped_column(String(128), default="main")
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    webhook_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    coverage_threshold: Mapped[int] = mapped_column(Integer, default=80)
    auth_method: Mapped[str] = mapped_column(String(16), default="none")
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_private_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    scan_root: Mapped[str] = mapped_column(String(255), default=".")
    test_suite_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ast_method_count: Mapped[int] = mapped_column(Integer, default=0)
    ast_api_count: Mapped[int] = mapped_column(Integer, default=0)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    gate_path_rules: Mapped[list | None] = mapped_column(JSON, nullable=True)
    high_risk_paths: Mapped[list | None] = mapped_column(JSON, nullable=True)
    low_risk_paths: Mapped[list | None] = mapped_column(JSON, nullable=True)
    high_risk_api_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    high_risk_symbol_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allow_self_override: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_notify_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notify_webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notify_policy: Mapped[str] = mapped_column(String(32), default="block_only")
    repo_type: Mapped[str] = mapped_column(String(20), default="backend")
    api_base_prefix: Mapped[str] = mapped_column(String(128), default="")
    api_strip_prefix: Mapped[str] = mapped_column(String(128), default="")
    linked_repo_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    repo_full_name: Mapped[str] = mapped_column(String(255))
    ref: Mapped[str] = mapped_column(String(255))
    base_sha: Mapped[str] = mapped_column(String(64))
    head_sha: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    affected_apis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    changed_symbols: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    gate_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    job_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class DiffGateUser(Base):
    """PAT 登录同步的 Git 身份与系统角色。"""

    __tablename__ = "diffgate_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), index=True)
    git_user_id: Mapped[str] = mapped_column(String(64), index=True)
    username: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    global_role: Mapped[str] = mapped_column(String(16), default="dev")
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    role_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    platform_provider: Mapped[str | None] = mapped_column(String(16), nullable=True)
    gitlab_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    platform_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserRepoGrant(Base):
    """仓库级 Git 权限映射（登录时刷新）。"""

    __tablename__ = "user_repo_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    repo_id: Mapped[str] = mapped_column(String(36), index=True)
    git_access_level: Mapped[str] = mapped_column(String(32), default="read")
    diffgate_role: Mapped[str] = mapped_column(String(16), default="dev")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )