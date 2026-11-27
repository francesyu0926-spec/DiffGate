"""用例集 Git 源连通性探测与本地/浅克隆用例预览。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Repository, TestSuite
from app.services.git_clone import _normalize_local_clone_url
from app.services.git_credential_chain import resolve_for_test_suite
from app.services.test_suite_git_fetch import ShallowCloneError, shallow_clone_with_credentials
from app.services.repo_detect_parse import (
    classify_clone_url,
    is_http_clone_url,
    is_local_clone_url,
    is_ssh_clone_url,
    validate_local_git_workspace,
)
from app.services.testcase_yaml_index import scan_yaml_tree


@dataclass
class ProbeResult:
    ok: bool
    message: str
    case_count: int = 0
    api_count: int = 0
    url_meta: dict | None = None
    credential_source: str | None = None
    repo_reachable: bool = False
    branch_exists: bool = False
    scan_path_exists: bool = False
    matched_files: int = 0
    sample_cases: list[dict] | None = None
    warnings: list[str] | None = None
    error_detail: str | None = None

    def as_dict(self) -> dict:
        out = {
            "ok": self.ok,
            "message": self.message,
            "case_count": self.case_count,
            "api_count": self.api_count,
            "repo_reachable": self.repo_reachable,
            "branch_exists": self.branch_exists,
            "scan_path_exists": self.scan_path_exists,
            "matched_files": self.matched_files,
        }
        if self.url_meta:
            out["url_meta"] = self.url_meta
        if self.credential_source:
            out["credential_source"] = self.credential_source
        if self.sample_cases is not None:
            out["sample_cases"] = self.sample_cases
        if self.warnings is not None:
            out["warnings"] = self.warnings
        if self.error_detail:
            out["error_detail"] = self.error_detail
        return out


def _attach_meta(result: ProbeResult, url_meta: dict | None) -> ProbeResult:
    result.url_meta = url_meta
    return result


def _resolve_git_url(db: Session, git_url: str | None, reuse_id: str | None) -> str:
    if reuse_id:
        repo = db.get(Repository, reuse_id.strip())
        if repo and (repo.clone_url or "").strip():
            return repo.clone_url.strip()
    return (git_url or "").strip()


def _binding_is_dynamic(raw_route: str, normalized_route: str) -> bool:
    raw = raw_route or ""
    if any(token in raw for token in ("${", "{{", "{", " + ")):
        return True
    norm = normalized_route or ""
    return "*" in norm and not norm.endswith("/*")


def _scan_counts(scan_root: Path, framework: str, suite_slug: str) -> tuple[int, int]:
    detail = _scan_preview_detail(scan_root, framework, suite_slug)
    return detail["total_cases"], detail["covered_api_count"]


def _scan_preview_detail(scan_root: Path, framework: str, suite_slug: str) -> dict:
    fw = (framework or "yaml").lower()
    empty = {
        "matched_files": 0,
        "total_cases": 0,
        "covered_api_count": 0,
        "sample_cases": [],
        "warnings": [],
        "dynamic_binding_count": 0,
    }
    if fw not in ("yaml", "httprunner", "apifox"):
        return empty
    parsed = scan_yaml_tree(scan_root, suite_slug=suite_slug or "probe", align_repo=None)
    file_paths = {c.file_path for c in parsed}
    route_keys: set[str] = set()
    dynamic_bindings = 0
    for case in parsed:
        for binding in case.bindings:
            route_keys.add(binding.contract_key or binding.normalized_route or binding.raw_route)
            if _binding_is_dynamic(binding.raw_route, binding.normalized_route):
                dynamic_bindings += 1
    warnings: list[str] = []
    if dynamic_bindings >= 2:
        warnings.append(
            f"有 {dynamic_bindings} 条用例的 URL 包含动态变量拼接，已自动归类为低置信度匹配"
        )
    sample_cases: list[dict] = []
    for case in parsed[:5]:
        binding = case.bindings[0] if case.bindings else None
        sample_cases.append(
            {
                "title": case.title,
                "method": binding.http_method if binding else "GET",
                "normalized_route": binding.normalized_route if binding else "",
                "file_path": case.file_path,
            }
        )
    return {
        "matched_files": len(file_paths),
        "total_cases": len(parsed),
        "covered_api_count": len(route_keys),
        "sample_cases": sample_cases,
        "warnings": warnings,
        "dynamic_binding_count": dynamic_bindings,
    }


def _local_probe(git_url: str, case_path: str | None, framework: str) -> ProbeResult:
    raw = _normalize_local_clone_url(git_url)
    root = Path(raw)
    if not root.exists():
        return ProbeResult(
            False,
            "路径不存在，请检查测试仓库地址或本地目录",
            error_detail="local_path_missing",
        )
    rel = (case_path or ".").strip() or "."
    scan_root = root / rel if rel != "." else root
    if not scan_root.exists():
        return ProbeResult(
            False,
            f"用例扫描目录不存在：{scan_root}",
            repo_reachable=True,
            branch_exists=True,
            scan_path_exists=False,
            error_detail="scan_path_missing",
        )
    detail = _scan_preview_detail(scan_root, framework, "probe")
    case_count = detail["total_cases"]
    api_count = detail["covered_api_count"]
    if case_count == 0 and (framework or "yaml").lower() in ("yaml", "httprunner", "apifox"):
        return ProbeResult(
            True,
            "目录可访问，未解析到 YAML 用例（请确认框架与扫描目录）",
            case_count=0,
            api_count=0,
            repo_reachable=True,
            branch_exists=True,
            scan_path_exists=True,
            matched_files=detail["matched_files"],
            sample_cases=detail["sample_cases"],
            warnings=detail["warnings"] or None,
        )
    fw = (framework or "yaml").lower()
    if fw not in ("yaml", "httprunner", "apifox"):
        return ProbeResult(
            True,
            f"仓库路径可访问；{fw} 解析器即将接入",
            case_count=0,
            api_count=0,
            repo_reachable=True,
            branch_exists=True,
            scan_path_exists=True,
        )
    return ProbeResult(
        True,
        f"探测到 {case_count} 条用例（绑定 {api_count} 个 API）",
        case_count=case_count,
        api_count=api_count,
        repo_reachable=True,
        branch_exists=True,
        scan_path_exists=True,
        matched_files=detail["matched_files"],
        sample_cases=detail["sample_cases"],
        warnings=detail["warnings"] or None,
    )


def _remote_shallow_probe(
    db: Session,
    git_url: str,
    branch: str | None,
    case_path: str | None,
    framework: str,
    git_auth_method: str | None,
    access_token: str | None,
    ssh_private_key: str | None,
    git_reuse_repository_id: str | None,
    bearer_session_token: str | None,
    suite: TestSuite | None = None,
    skip_ssl_verify: bool | None = None,
) -> ProbeResult:
    creds = resolve_for_test_suite(
        db,
        clone_url=git_url,
        suite=suite,
        git_auth_method=git_auth_method,
        access_token=access_token,
        ssh_private_key=ssh_private_key,
        git_reuse_repository_id=git_reuse_repository_id,
        bearer_session_token=bearer_session_token,
    )

    try:
        dest = shallow_clone_with_credentials(
            git_url,
            branch,
            creds,
            skip_ssl_verify=skip_ssl_verify,
        )
    except ShallowCloneError as exc:
        msg = exc.message or "仓库拉取失败"
        branch_ok = "分支" not in msg and "branch" not in msg.lower()
        return ProbeResult(
            False,
            msg,
            credential_source=exc.credential_source or creds.credential_source,
            repo_reachable=False,
            branch_exists=branch_ok,
            scan_path_exists=False,
            error_detail=msg,
        )

    try:
        cred_note = f"（凭据：{creds.source_label}）" if creds.source_label else ""
        rel = (case_path or ".").strip() or "."
        scan_root = dest / rel if rel != "." else dest
        if not scan_root.exists():
            return ProbeResult(
                True,
                f"仓库可拉取，但用例扫描目录在仓库中不存在{cred_note}",
                case_count=0,
                api_count=0,
                credential_source=creds.credential_source,
                repo_reachable=True,
                branch_exists=True,
                scan_path_exists=False,
            )
        detail = _scan_preview_detail(scan_root, framework, "probe")
        case_count = detail["total_cases"]
        api_count = detail["covered_api_count"]
        if case_count == 0:
            return ProbeResult(
                True,
                f"仓库可拉取，当前目录下未解析到 YAML 用例{cred_note}",
                case_count=0,
                api_count=0,
                credential_source=creds.credential_source,
                repo_reachable=True,
                branch_exists=True,
                scan_path_exists=True,
                matched_files=detail["matched_files"],
                sample_cases=detail["sample_cases"],
                warnings=detail["warnings"] or None,
            )
        return ProbeResult(
            True,
            f"探测到 {case_count} 条用例（绑定 {api_count} 个 API）{cred_note}",
            case_count=case_count,
            api_count=api_count,
            credential_source=creds.credential_source,
            repo_reachable=True,
            branch_exists=True,
            scan_path_exists=True,
            matched_files=detail["matched_files"],
            sample_cases=detail["sample_cases"],
            warnings=detail["warnings"] or None,
        )
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def probe_suite_source(
    db: Session,
    *,
    git_url: str | None,
    git_reuse_repository_id: str | None,
    git_branch: str | None,
    case_path: str | None,
    framework: str | None,
    git_auth_method: str | None,
    access_token: str | None,
    ssh_private_key: str | None,
    bearer_session_token: str | None = None,
    suite: TestSuite | None = None,
    skip_ssl_verify: bool | None = None,
) -> ProbeResult:
    resolved = _resolve_git_url(db, git_url, git_reuse_repository_id)
    if not resolved:
        return ProbeResult(False, "请填写测试仓库地址或选择复用业务仓库")

    url_meta = classify_clone_url(resolved, None)

    if is_local_clone_url(resolved) or (url_meta.get("transport") == "local"):
        valid, msg = validate_local_git_workspace(resolved)
        if not valid:
            return _attach_meta(ProbeResult(False, msg), url_meta)
        return _attach_meta(_local_probe(resolved, case_path, framework or "yaml"), url_meta)

    if is_ssh_clone_url(resolved) or is_http_clone_url(resolved):
        ssl_skip = skip_ssl_verify
        if ssl_skip is None and suite is not None:
            ssl_skip = bool(getattr(suite, "skip_ssl_verify", False))
        result = _remote_shallow_probe(
            db,
            resolved,
            git_branch,
            case_path,
            framework or "yaml",
            git_auth_method or "inherit",
            access_token,
            ssh_private_key,
            git_reuse_repository_id,
            bearer_session_token,
            suite,
            ssl_skip,
        )
        return _attach_meta(result, url_meta)

    return _attach_meta(
        ProbeResult(False, url_meta.get("message") or "无法识别的仓库地址"),
        url_meta,
    )


def probe_from_suite_row(
    db: Session,
    row: TestSuite,
    *,
    bearer_session_token: str | None = None,
) -> ProbeResult:
    return probe_suite_source(
        db,
        git_url=row.git_url,
        git_reuse_repository_id=row.git_reuse_repository_id,
        git_branch=row.git_branch,
        case_path=row.case_path,
        framework=row.framework,
        git_auth_method=getattr(row, "git_auth_method", None) or "inherit",
        access_token=None,
        ssh_private_key=None,
        bearer_session_token=bearer_session_token,
        suite=row,
    )