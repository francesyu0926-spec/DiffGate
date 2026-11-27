"""用例集「连通性 + 用例预览」：复用 probe_suite_source（凭据链 / 地址解析 / YAML 索引）。"""

from __future__ import annotations

import concurrent.futures
import time

from sqlalchemy.orm import Session

from app.db.models import TestSuite
from app.services.repo_branch_detect import _sanitize_error_message
from app.services.test_suite_probe import ProbeResult, probe_suite_source

_PREVIEW_TIMEOUT_SEC = 5.0


def _auth_from_credential_mode(mode: str | None) -> str:
    m = (mode or "auto").lower()
    if m == "token":
        return "token"
    if m == "ssh":
        return "ssh"
    return "inherit"


def _preview_impl(
    db: Session,
    *,
    clone_url: str | None,
    linked_repo_id: str | None,
    credential_mode: str,
    access_token: str | None,
    ssh_private_key: str | None,
    verify_ssl: bool,
    branch: str | None,
    scan_path: str | None,
    framework: str | None,
    bearer_session_token: str | None,
    suite: TestSuite | None,
) -> ProbeResult:
    return probe_suite_source(
        db,
        git_url=clone_url,
        git_reuse_repository_id=linked_repo_id,
        git_branch=(branch or "main").strip() or "main",
        case_path=(scan_path or "").strip() or None,
        framework=framework or "yaml",
        git_auth_method=_auth_from_credential_mode(credential_mode),
        access_token=access_token,
        ssh_private_key=ssh_private_key,
        bearer_session_token=bearer_session_token,
        suite=suite,
        skip_ssl_verify=not verify_ssl,
    )


def _result_to_preview_payload(result: ProbeResult, *, latency_ms: int) -> dict:
    ok = bool(result.ok)
    total = int(result.case_count or 0)
    covered = int(result.api_count or 0)
    matched_files = int(result.matched_files or 0)
    summary = {
        "matched_files": matched_files,
        "total_cases": total,
        "covered_api_count": covered,
    }
    sample_cases = list(result.sample_cases or [])
    warnings = list(result.warnings or [])
    err_detail = _sanitize_error_message(result.error_detail or (result.message if not ok else None))

    message = result.message or ""
    if ok and total > 0:
        message = (
            f"✓ 连通成功，探测到 {total} 条用例（{matched_files} 个文件，绑定 {covered} 个 API）"
        )
    elif ok and total == 0 and not message.startswith("✓"):
        message = f"✓ {message}"

    return {
        "success": ok,
        "latency_ms": latency_ms,
        "repo_reachable": bool(result.repo_reachable),
        "branch_exists": bool(result.branch_exists),
        "scan_path_exists": bool(result.scan_path_exists),
        "summary": summary,
        "sample_cases": sample_cases,
        "warnings": warnings,
        "error_detail": err_detail if not ok else None,
        "message": message,
        "credential_source": result.credential_source,
        "url_meta": result.url_meta,
    }


def preview_suite_source(
    db: Session,
    *,
    source_type: str,
    clone_url: str | None,
    linked_repo_id: str | None,
    credential_mode: str = "auto",
    access_token: str | None = None,
    ssh_private_key: str | None = None,
    verify_ssl: bool = True,
    branch: str | None = "main",
    scan_path: str | None = None,
    framework: str | None = "yaml",
    bearer_session_token: str | None = None,
    suite: TestSuite | None = None,
) -> dict:
    """
    连通性 → 分支/目录校验 → 浅克隆扫描 → 返回用例数与 API 绑定数。
    总耗时上限 5s（超时则 success=false）。
    """
    started = time.perf_counter()
    if (source_type or "git").lower() != "git":
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "success": False,
            "latency_ms": latency_ms,
            "repo_reachable": False,
            "branch_exists": False,
            "scan_path_exists": False,
            "summary": {"matched_files": 0, "total_cases": 0, "covered_api_count": 0},
            "sample_cases": [],
            "warnings": [],
            "error_detail": "preview_source_not_git",
            "message": "当前仅支持 Git 测试仓库预览；Webhook 来源请保存后由流水线触发验证",
            "credential_source": None,
            "url_meta": None,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            _preview_impl,
            db,
            clone_url=(clone_url or "").strip() or None,
            linked_repo_id=linked_repo_id,
            credential_mode=credential_mode,
            access_token=access_token,
            ssh_private_key=ssh_private_key,
            verify_ssl=verify_ssl,
            branch=branch,
            scan_path=scan_path,
            framework=framework,
            bearer_session_token=bearer_session_token,
            suite=suite,
        )
        try:
            result: ProbeResult = future.result(timeout=_PREVIEW_TIMEOUT_SEC)
        except concurrent.futures.TimeoutError:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return {
                "success": False,
                "latency_ms": latency_ms,
                "repo_reachable": False,
                "branch_exists": False,
                "scan_path_exists": False,
                "summary": {"matched_files": 0, "total_cases": 0, "covered_api_count": 0},
                "sample_cases": [],
                "warnings": [],
                "error_detail": "preview_timeout",
                "message": "预览超时（5 秒）：请检查网络、分支或用例扫描目录是否正确",
                "credential_source": None,
                "url_meta": None,
            }

    latency_ms = int((time.perf_counter() - started) * 1000)
    return _result_to_preview_payload(result, latency_ms=latency_ms)