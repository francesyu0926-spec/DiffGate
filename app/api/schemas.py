from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


AuthMethod = Literal["none", "token", "ssh"]
GateStatus = Literal["PASS", "BLOCK", "PENDING", "OVERRIDDEN"]
OverrideReasonCategory = Literal[
    "hotfix",
    "branch_unsimulatable",
    "non_core_reviewed",
    "fe_be_coordinated",
    "other",
]


class CoverageProbeLine(BaseModel):
    file: str = Field(..., min_length=1, max_length=512)
    line: int = Field(..., ge=1)
    covered: bool | None = None
    prefix: str = "+"
    ignored: bool = False
    filter_reason: str | None = None
    branch_partial: bool = False


class GateOverrideIn(BaseModel):
    """人工豁免放行（仅 BLOCK 批次）。"""

    reason_category: OverrideReasonCategory
    reason_detail: str = Field(..., min_length=2, max_length=2000)


class RepositoryBranchesIn(BaseModel):
    clone_url: str | None = Field(default=None, max_length=512)
    credential_mode: Literal["auto", "token", "ssh"] = "auto"
    access_token: str | None = Field(default=None, max_length=4096)
    ssh_private_key: str | None = Field(default=None, max_length=65535)
    verify_ssl: bool = True
    linked_repo_id: str | None = Field(default=None, max_length=36)
    test_suite_id: str | None = Field(
        default=None,
        max_length=36,
        description="编辑用例集时用于读取已保存凭据（可选）",
    )


class RepositoryBranchItem(BaseModel):
    name: str
    is_default: bool = False


class RepositoryBranchesOut(BaseModel):
    success: bool
    source: str = "none"
    default_branch: str = "main"
    branches: list[RepositoryBranchItem] = Field(default_factory=list)
    error_message: str | None = None


class CloneUrlParseIn(BaseModel):
    clone_url: str = Field(..., min_length=1, max_length=512)
    provider: str | None = Field(default=None, pattern="^(github|gitlab|local)$")


class DetectRepositoryIn(BaseModel):
    clone_url: str = Field(..., min_length=1, max_length=512)
    source_type: str = Field(default="gitlab", pattern="^(github|gitlab|local)$")
    auth_mode: AuthMethod = "none"
    custom_token: str | None = Field(default=None, max_length=4096)
    branch: str | None = Field(default=None, max_length=128)
    provider: str | None = Field(default=None, pattern="^(github|gitlab|local)$")
    default_branch: str | None = Field(default=None, max_length=128)

    @model_validator(mode="before")
    @classmethod
    def _legacy_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if data.get("provider") and not data.get("source_type"):
            data["source_type"] = data["provider"]
        if data.get("default_branch") and not data.get("branch"):
            data["branch"] = data["default_branch"]
        return data


class MonorepoCandidateIn(BaseModel):
    repo_type_id: str = Field(..., max_length=32)
    scan_root: str = Field(default=".", max_length=255)


class RepositoryMonorepoBundleIn(BaseModel):
    """同一 Clone URL 一键创建前后端两条记录并互相关联。"""

    clone_url: str = Field(..., min_length=1, max_length=512)
    provider: str = Field(..., pattern="^(github|gitlab|local)$")
    default_branch: str = Field(default="main", max_length=128)
    base_full_name: str = Field(..., min_length=1, max_length=255)
    candidates: list[MonorepoCandidateIn] = Field(..., min_length=2, max_length=8)
    description: str | None = Field(default=None, max_length=512)
    enabled: bool = True
    webhook_enabled: bool = True
    coverage_threshold: int = Field(default=80, ge=0, le=100)


class TestNotifyIn(BaseModel):
    """向 IM Webhook 发送测试消息（无需先保存仓库）。"""

    webhook_url: str = Field(..., min_length=8, max_length=512)


class RepositoryAnalyzeIn(BaseModel):
    """手动触发分析：可选目标分支与基准分支（三点 diff）。"""

    branch: str | None = Field(default=None, max_length=255, description="待测分支，默认仓库 default_branch")
    base_branch: str | None = Field(
        default=None,
        max_length=255,
        description="对比基准分支；设置后 base=merge-base(base_branch, branch)",
    )


class GateReportIn(BaseModel):
    """精准回归 / CI 回传增量覆盖率与用例结果。"""

    incremental_coverage_pct: float = Field(..., ge=0, le=100)
    tests_passed: bool = True
    coverage_probes: list[CoverageProbeLine] | None = None
    branch_coverage_pct: float | None = Field(default=None, ge=0, le=100)
    running_commit_sha: str | None = Field(
        default=None,
        max_length=64,
        description="测试环境当前运行代码的 commit（git rev-parse HEAD 或 CI 变量）",
    )


class RepositoryCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255, examples=["acme/order-service"])
    provider: str = Field(..., pattern="^(github|gitlab|local)$")
    clone_url: str = Field(..., min_length=1, max_length=512)
    default_branch: str = Field(default="main", max_length=128)
    description: str | None = Field(default=None, max_length=512)
    enabled: bool = True
    webhook_enabled: bool = True
    coverage_threshold: int = Field(default=80, ge=0, le=100)
    auth_method: AuthMethod = "none"
    access_token: str | None = Field(default=None, max_length=4096)
    ssh_private_key: str | None = Field(default=None, max_length=16384)
    scan_root: str = Field(default=".", max_length=255)
    test_suite_id: str | None = Field(default=None, max_length=128)
    gate_path_rules: list[dict] | None = None
    high_risk_paths: list[str] | None = None
    low_risk_paths: list[str] | None = None
    high_risk_api_threshold: int | None = Field(default=None, ge=1, le=100)
    high_risk_symbol_threshold: int | None = Field(default=None, ge=1, le=500)
    allow_self_override: bool = False
    webhook_notify_url: str | None = Field(default=None, max_length=512)
    notify_webhook_url: str | None = Field(default=None, max_length=512)
    notify_policy: Literal["off", "block_only", "always"] = "block_only"
    repo_type: str = Field(
        default="backend_python",
        max_length=32,
        pattern="^(auto|backend_python|backend|frontend|backend_node|backend_go|backend_java)$",
    )
    api_base_prefix: str = Field(default="", max_length=128)
    api_strip_prefix: str = Field(default="", max_length=128)
    linked_repo_ids: list[str] = Field(default_factory=list)


class RepositoryUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    provider: str | None = Field(default=None, pattern="^(github|gitlab|local)$")
    clone_url: str | None = Field(default=None, min_length=1, max_length=512)
    default_branch: str | None = Field(default=None, max_length=128)
    description: str | None = None
    enabled: bool | None = None
    webhook_enabled: bool | None = None
    coverage_threshold: int | None = Field(default=None, ge=0, le=100)
    auth_method: AuthMethod | None = None
    access_token: str | None = Field(default=None, max_length=4096)
    ssh_private_key: str | None = Field(default=None, max_length=16384)
    scan_root: str | None = Field(default=None, max_length=255)
    test_suite_id: str | None = Field(default=None, max_length=128)
    gate_path_rules: list[dict] | None = None
    high_risk_paths: list[str] | None = None
    low_risk_paths: list[str] | None = None
    high_risk_api_threshold: int | None = Field(default=None, ge=1, le=100)
    high_risk_symbol_threshold: int | None = Field(default=None, ge=1, le=500)
    allow_self_override: bool | None = None
    webhook_notify_url: str | None = Field(default=None, max_length=512)
    notify_webhook_url: str | None = Field(default=None, max_length=512)
    notify_policy: Literal["off", "block_only", "always"] | None = None
    repo_type: str | None = Field(default=None, max_length=32)
    api_base_prefix: str | None = Field(default=None, max_length=128)
    api_strip_prefix: str | None = Field(default=None, max_length=128)
    linked_repo_ids: list[str] | None = None


class RepositoryOut(BaseModel):
    id: str
    full_name: str
    provider: str
    clone_url: str
    default_branch: str
    description: str | None
    enabled: bool
    webhook_enabled: bool
    coverage_threshold: int
    auth_method: str
    scan_root: str
    test_suite_id: str | None
    gate_path_rules: list[dict] | None = None
    high_risk_paths: list[str] | None = None
    low_risk_paths: list[str] | None = None
    high_risk_api_threshold: int | None = None
    high_risk_symbol_threshold: int | None = None
    allow_self_override: bool = False
    webhook_notify_url: str | None = None
    notify_webhook_url: str | None = None
    notify_policy: str = "block_only"
    repo_type: str = "backend"
    api_base_prefix: str = ""
    api_strip_prefix: str = ""
    linked_repo_ids: list[str] | None = None
    token_configured: bool = False
    ssh_configured: bool = False
    ast_method_count: int
    ast_api_count: int
    last_indexed_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


TestSuiteSourceType = Literal["git", "webhook", "manual"]
TestSuiteFramework = Literal["yaml", "pytest", "httprunner", "apifox", "junit", "gotest"]
TestSuiteGitAuthMethod = Literal["inherit", "token", "ssh"]


class TestSuiteCreate(BaseModel):
    slug: str = Field(..., min_length=2, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=512)
    external_ref: str | None = Field(default=None, max_length=255)
    enabled: bool = True
    source_type: TestSuiteSourceType = "manual"
    git_url: str | None = Field(default=None, max_length=512)
    git_branch: str | None = Field(default=None, max_length=128)
    case_path: str | None = Field(default=None, max_length=255)
    framework: TestSuiteFramework | None = None
    git_reuse_repository_id: str | None = Field(default=None, max_length=36)
    git_auth_method: TestSuiteGitAuthMethod = "inherit"
    access_token: str | None = Field(default=None, max_length=4096)
    ssh_private_key: str | None = Field(default=None, max_length=65535)
    skip_ssl_verify: bool = False
    trigger_webhook_url: str | None = Field(default=None, max_length=512)
    repository_ids: list[str] | None = None


class TestSuitePreviewCaseSample(BaseModel):
    title: str
    method: str = "GET"
    normalized_route: str = ""
    file_path: str = ""


class TestSuitePreviewSummary(BaseModel):
    matched_files: int = 0
    total_cases: int = 0
    covered_api_count: int = 0


class TestSuitePreviewOut(BaseModel):
    success: bool
    latency_ms: int = 0
    repo_reachable: bool = False
    branch_exists: bool = False
    scan_path_exists: bool = False
    summary: TestSuitePreviewSummary
    sample_cases: list[TestSuitePreviewCaseSample] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_detail: str | None = None
    message: str | None = None
    credential_source: str | None = None


class TestSuitePreviewIn(BaseModel):
    source_type: TestSuiteSourceType = "git"
    clone_url: str | None = Field(default=None, max_length=512)
    linked_repo_id: str | None = Field(default=None, max_length=36)
    credential_mode: Literal["auto", "token", "ssh"] = "auto"
    access_token: str | None = Field(default=None, max_length=4096)
    ssh_private_key: str | None = Field(default=None, max_length=65535)
    verify_ssl: bool = True
    branch: str | None = Field(default="main", max_length=128)
    scan_path: str | None = Field(default=None, max_length=255)
    framework: TestSuiteFramework | None = "yaml"
    test_suite_id: str | None = Field(default=None, max_length=36)


class TestSuiteProbeIn(BaseModel):
    git_url: str | None = Field(default=None, max_length=512)
    git_branch: str | None = Field(default=None, max_length=128)
    case_path: str | None = Field(default=None, max_length=255)
    framework: TestSuiteFramework | None = "yaml"
    git_reuse_repository_id: str | None = Field(default=None, max_length=36)
    git_auth_method: TestSuiteGitAuthMethod = "inherit"
    access_token: str | None = Field(default=None, max_length=4096)
    ssh_private_key: str | None = Field(default=None, max_length=65535)
    skip_ssl_verify: bool | None = None


class TestSuiteBranchesIn(BaseModel):
    git_url: str | None = Field(default=None, max_length=512)
    git_reuse_repository_id: str | None = Field(default=None, max_length=36)
    git_auth_method: TestSuiteGitAuthMethod = "inherit"
    access_token: str | None = Field(default=None, max_length=4096)
    ssh_private_key: str | None = Field(default=None, max_length=65535)
    skip_ssl_verify: bool | None = None
    test_suite_id: str | None = Field(default=None, max_length=36)


class TestSuiteUpdate(BaseModel):
    slug: str | None = Field(default=None, min_length=2, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=512)
    external_ref: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    source_type: TestSuiteSourceType | None = None
    git_url: str | None = Field(default=None, max_length=512)
    git_branch: str | None = Field(default=None, max_length=128)
    case_path: str | None = Field(default=None, max_length=255)
    framework: TestSuiteFramework | None = None
    git_reuse_repository_id: str | None = Field(default=None, max_length=36)
    git_auth_method: TestSuiteGitAuthMethod | None = None
    access_token: str | None = Field(default=None, max_length=4096)
    ssh_private_key: str | None = Field(default=None, max_length=65535)
    skip_ssl_verify: bool | None = None
    trigger_webhook_url: str | None = Field(default=None, max_length=512)
    repository_ids: list[str] | None = None


class TestSuiteOut(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    external_ref: str | None
    enabled: bool
    source_type: str = "manual"
    git_url: str | None = None
    git_branch: str | None = None
    case_path: str | None = None
    framework: str | None = None
    git_reuse_repository_id: str | None = None
    git_auth_method: str = "inherit"
    skip_ssl_verify: bool = False
    trigger_webhook_url: str | None = None
    indexed_api_count: int = 0
    case_count: int = 0
    last_synced_at: datetime | None = None
    repo_count: int = 0
    linked_repository_ids: list[str] = []
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class TestSuitePresetOut(BaseModel):
    slug: str
    name: str
    description: str | None = None