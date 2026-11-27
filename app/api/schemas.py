from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
    covered: bool
    prefix: str = "+"


class GateOverrideIn(BaseModel):
    """人工豁免放行（仅 BLOCK 批次）。"""

    reason_category: OverrideReasonCategory
    reason_detail: str = Field(..., min_length=2, max_length=2000)


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
        pattern="^(backend_python|backend|frontend|backend_node|backend_go|backend_java)$",
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