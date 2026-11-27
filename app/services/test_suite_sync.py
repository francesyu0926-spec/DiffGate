"""用例集索引同步（Git 扫描解析将逐步落地，当前为配置校验 + 占位索引）。"""

from __future__ import annotations

from datetime import datetime, timezone
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Repository, TestSuite
from dataclasses import dataclass

from app.services.git_clone import _normalize_local_clone_url
from app.services.git_credential_chain import resolve_for_test_suite
from app.services.repo_detect_parse import is_http_clone_url, is_local_clone_url, is_ssh_clone_url
from app.services.test_suite_git_fetch import ShallowCloneError, shallow_clone_with_credentials
from app.services.testcase_index_store import SyncIndexStats, merge_suite_index
from app.services.testcase_yaml_index import scan_yaml_tree


@dataclass
class SuiteSyncResult:
    message: str
    stats: SyncIndexStats | None = None
    skipped: bool = False

    def as_dict(self) -> dict:
        out: dict = {"message": self.message, "skipped": self.skipped}
        if self.stats:
            out["sync_stats"] = {
                "added": self.stats.added,
                "updated": self.stats.updated,
                "removed": self.stats.removed,
                "api_count": self.stats.api_count,
                "case_count": self.stats.case_count,
            }
        return out


def _strip_opt(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    return s or None


def _apply_source_fields(row: TestSuite, data: dict) -> None:
    if "source_type" in data and data["source_type"]:
        row.source_type = data["source_type"]
    for key in (
        "git_url",
        "git_branch",
        "case_path",
        "framework",
        "git_reuse_repository_id",
        "git_auth_method",
        "access_token",
        "ssh_private_key",
        "skip_ssl_verify",
        "trigger_webhook_url",
    ):
        if key in data:
            row.__setattr__(key, _strip_opt(data.get(key)))


def bind_repositories(db: Session, suite: TestSuite, repository_ids: list[str] | None) -> None:
    if repository_ids is None:
        return
    slug = suite.slug
    desired = set(repository_ids)
    linked = db.scalars(select(Repository).where(Repository.test_suite_id == slug)).all()
    for repo in linked:
        if repo.id not in desired:
            repo.test_suite_id = None
    for rid in desired:
        repo = db.get(Repository, rid)
        if repo:
            repo.test_suite_id = slug


def linked_repository_ids(db: Session, slug: str) -> list[str]:
    rows = db.scalars(select(Repository.id).where(Repository.test_suite_id == slug)).all()
    return list(rows)


def _align_repo_for_suite(db: Session, suite: TestSuite) -> Repository | None:
    reuse_id = (suite.git_reuse_repository_id or "").strip()
    if reuse_id:
        row = db.get(Repository, reuse_id)
        if row:
            return row
    return db.scalar(
        select(Repository).where(Repository.test_suite_id == suite.slug).order_by(Repository.full_name.asc())
    )


def sync_test_suite(
    db: Session,
    suite: TestSuite,
    *,
    bearer_session_token: str | None = None,
) -> SuiteSyncResult:
    source = (suite.source_type or "manual").lower()
    if source == "manual":
        return SuiteSyncResult("手工登记模式无需同步索引", skipped=True)
    if source == "webhook":
        suite.last_synced_at = datetime.now(timezone.utc)
        return SuiteSyncResult("Webhook 模式由外部平台推送执行结果；已刷新同步时间", skipped=True)

    git_url = (suite.git_url or "").strip()
    reuse_id = (suite.git_reuse_repository_id or "").strip()
    if reuse_id:
        repo = db.get(Repository, reuse_id)
        if repo:
            git_url = (repo.clone_url or "").strip()
    if not git_url:
        return SuiteSyncResult("未配置测试仓库地址，无法同步", skipped=True)

    case_path = (suite.case_path or ".").strip() or "."
    stats: SyncIndexStats | None = None
    framework = (suite.framework or "yaml").lower()
    align_repo = _align_repo_for_suite(db, suite)
    remote_tmp: Path | None = None

    def _scan_tree(scan_root: Path) -> SuiteSyncResult:
        nonlocal stats
        if framework in ("yaml", "httprunner", "apifox"):
            parsed = scan_yaml_tree(scan_root, suite_slug=suite.slug, align_repo=align_repo)
            stats = merge_suite_index(db, suite.id, parsed)
            msg = stats.summary_message()
            suite.indexed_api_count = stats.api_count
            suite.case_count = stats.case_count
            return SuiteSyncResult(msg, stats=stats)
        suite.indexed_api_count = 0
        suite.case_count = 0
        return SuiteSyncResult(f"{framework} 解析器即将接入，当前仅保存配置")

    try:
        if is_local_clone_url(git_url):
            root = Path(_normalize_local_clone_url(git_url))
            if not root.exists():
                return SuiteSyncResult(f"本地路径不存在：{root}", skipped=True)
            scan_root = root / case_path if case_path != "." else root
            result = _scan_tree(scan_root)
        elif is_ssh_clone_url(git_url) or is_http_clone_url(git_url):
            creds = resolve_for_test_suite(
                db,
                clone_url=git_url,
                suite=suite,
                git_auth_method=getattr(suite, "git_auth_method", None) or "inherit",
                access_token=None,
                ssh_private_key=None,
                git_reuse_repository_id=reuse_id or None,
                bearer_session_token=bearer_session_token,
            )
            try:
                remote_tmp = shallow_clone_with_credentials(
                    git_url,
                    suite.git_branch,
                    creds,
                    skip_ssl_verify=getattr(suite, "skip_ssl_verify", False) or None,
                )
            except ShallowCloneError as exc:
                suite.indexed_api_count = 0
                suite.case_count = 0
                return SuiteSyncResult(exc.message, skipped=True)
            scan_root = remote_tmp / case_path if case_path != "." else remote_tmp
            result = _scan_tree(scan_root)
            if creds.source_label:
                result.message = f"{result.message}（凭据：{creds.source_label}）"
        else:
            suite.indexed_api_count = 0
            suite.case_count = 0
            result = SuiteSyncResult("未识别的仓库地址或路径不存在", skipped=True)
    finally:
        if remote_tmp is not None:
            shutil.rmtree(remote_tmp, ignore_errors=True)

    suite.last_synced_at = datetime.now(timezone.utc)
    return result