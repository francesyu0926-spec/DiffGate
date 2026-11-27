"""三级仓库探测：本地 → 平台 API → 浅克隆。"""

from __future__ import annotations

import concurrent.futures
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.adapters.registry import list_repo_type_options
from app.config import get_settings
from app.services.repo_detect_fingerprint import (
    FingerprintResult,
    collect_local_paths,
    detect_from_directory,
    detect_from_paths,
    suggest_project_name,
)
from app.services.repo_directory_analyzer import analyzed_candidates_for_api, repo_id_from_detected_type, run_directory_analysis
from app.services.repo_scan_directories import build_directories
from app.services.repo_detect_parse import classify_clone_url, parse_clone_url_meta, resolve_effective_provider
from app.services.repo_detect_remote import fetch_github_tree, fetch_gitlab_tree

_DETECT_TIMEOUT_SEC = 5.0

_REPO_LABEL = {r["id"]: r["label"] for r in list_repo_type_options()}


@dataclass
class DetectResult:
    repo_type: str
    scan_root: str
    label: str
    confidence: str = "medium"
    monorepo_hint: str | None = None
    candidates: list[dict] | None = None
    success: bool = True
    suggested_name: str | None = None
    default_branch: str = "main"
    is_monorepo: bool = False
    detected_type: str | None = None
    suggested_scan_root: str | None = None
    framework: str | None = None
    directories: list[dict] | None = None

    clone_url_meta: dict | None = None
    error_message: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["suggested_scan_root"] = data.get("suggested_scan_root") or self.scan_root
        data["recommended_root"] = data["suggested_scan_root"]
        data["detected_type"] = data.get("detected_type") or self.repo_type
        dirs = self.directories or []
        data["directories"] = dirs
        data["scan_directories"] = [
            {"path": d.get("path"), "recommended": bool(d.get("is_recommended"))} for d in dirs
        ]
        data["error_message"] = self.error_message
        if self.clone_url_meta:
            data["clone_url_meta"] = self.clone_url_meta
        return data


def _label(repo_type: str) -> str:
    return _REPO_LABEL.get(repo_type, repo_type)


def _monorepo_hint_text(candidates: list[dict] | None) -> str | None:
    if not candidates or len(candidates) < 2:
        return None
    parts = [f"「{c.get('label', '')}，目录 {c.get('scan_root', '.')}」" for c in candidates[:4]]
    return (
        "检测到当前仓库同时包含前后端模块（Monorepo）："
        + "、".join(parts)
        + "。同一地址可添加多次并分别指定源码根目录，或使用一键双建。"
    )


def _from_fingerprint(
    fp: FingerprintResult,
    *,
    suggested_name: str | None,
    branch: str,
    clone_url: str,
    paths: set[str] | None = None,
    contents: dict[str, str] | None = None,
    repo_dir: Path | None = None,
) -> DetectResult:
    base_name = suggested_name or suggest_project_name(clone_url) or "project"
    analyzed = run_directory_analysis(paths=paths, contents=contents, repo_dir=repo_dir)
    dir_tree = build_directories(fp, paths=paths, contents=contents, repo_dir=repo_dir)

    analyzed_cands = analyzed.get("candidates") or []
    if analyzed_cands:
        cands = analyzed_candidates_for_api(analyzed)
        detected_type = str(analyzed.get("detected_type") or fp.detected_type)
        repo_type = repo_id_from_detected_type(detected_type)
        scan_root = str(analyzed.get("recommended_root") or fp.scan_root)
        is_monorepo = bool(analyzed.get("is_monorepo"))
        confidence = "high"
        framework = next(
            (c.get("framework") for c in analyzed_cands if c.get("scan_root") == scan_root),
            fp.framework,
        )
    else:
        cands = [c.to_dict() for c in fp.candidates] if fp.candidates else None
        repo_type = fp.repo_type
        scan_root = fp.scan_root
        is_monorepo = fp.is_monorepo
        detected_type = fp.detected_type
        confidence = fp.confidence
        framework = fp.framework

    return DetectResult(
        repo_type=repo_type,
        scan_root=scan_root,
        label=_label(repo_type),
        confidence=confidence,
        monorepo_hint=_monorepo_hint_text(cands),
        candidates=cands,
        suggested_name=base_name,
        default_branch=branch or "main",
        is_monorepo=is_monorepo,
        detected_type=detected_type,
        suggested_scan_root=scan_root,
        framework=framework,
        directories=dir_tree,
    )


def _local_detect(clone_url: str) -> tuple[FingerprintResult, str, set[str], dict[str, str], Path]:
    path = Path(clone_url.strip().strip('"').replace("file://", ""))
    if not path.is_dir():
        raise FileNotFoundError(f"本地路径不存在：{path}")
    resolved = path.resolve()
    paths, contents = collect_local_paths(resolved)
    fp = detect_from_paths(paths, contents)
    return fp, path.name, paths, contents, resolved


def _api_detect(
    *,
    source_type: str,
    clone_url: str,
    token: str | None,
    branch: str | None,
) -> tuple[FingerprintResult, str, set[str], dict[str, str]] | None:
    meta = parse_clone_url_meta(clone_url, source_type)
    if not meta or meta.provider == "local":
        return None
    try:
        if meta.provider == "github":
            paths, contents, resolved = fetch_github_tree(meta, token, branch)
        else:
            paths, contents, resolved = fetch_gitlab_tree(
                meta,
                token,
                branch,
                meta.base_url,
                clone_url=clone_url,
            )
        fp = detect_from_paths(paths, contents)
        return fp, resolved, paths, contents
    except Exception:
        return None


def _sparse_clone_detect(
    *,
    clone_url: str,
    branch: str | None,
) -> tuple[FingerprintResult, str, set[str], dict[str, str]]:
    tmp = (Path(get_settings().local_data_dir) / "tmp" / f"detect-{uuid.uuid4().hex}").resolve()
    tmp.parent.mkdir(parents=True, exist_ok=True)
    br = branch or "main"
    cmd = [
        "git",
        "clone",
        "--depth=1",
        "--filter=blob:limit=100k",
        "--single-branch",
        "--branch",
        br,
        clone_url,
        str(tmp),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        if proc.returncode != 0:
            cmd_no_filter = [
                "git",
                "clone",
                "--depth=1",
                "--single-branch",
                "--branch",
                br,
                clone_url,
                str(tmp),
            ]
            proc = subprocess.run(cmd_no_filter, capture_output=True, text=True, timeout=30, check=False)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "git clone failed").strip()[:400])
        paths, contents = collect_local_paths(tmp)
        fp = detect_from_paths(paths, contents)
        return fp, br, paths, contents
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def detect_repository_profile(
    *,
    source_type: str,
    clone_url: str,
    branch: str | None = None,
    auth_mode: str = "none",
    custom_token: str | None = None,
    provider: str | None = None,
    default_branch: str | None = None,
) -> DetectResult:
    """对外统一入口（兼容 provider / default_branch 旧字段）。"""
    explicit = (source_type or provider or "").strip().lower() or None
    st = resolve_effective_provider(clone_url, explicit)
    url_meta = classify_clone_url(clone_url, explicit)
    br_in = branch or default_branch
    token = (custom_token or "").strip() or None
    if auth_mode == "none":
        token = token  # 仍可传 custom_token
    suggested = suggest_project_name(clone_url)

    def _run() -> DetectResult:
        def _finish(dr: DetectResult) -> DetectResult:
            dr.clone_url_meta = url_meta
            return dr

        if st == "local":
            fp, _, paths, contents, repo_dir = _local_detect(clone_url)
            return _finish(
                _from_fingerprint(
                    fp,
                    suggested_name=suggested,
                    branch=br_in or "main",
                    clone_url=clone_url,
                    paths=paths,
                    contents=contents,
                    repo_dir=repo_dir,
                )
            )

        api_hit = _api_detect(source_type=st, clone_url=clone_url, token=token, branch=br_in)
        if api_hit:
            fp, resolved, paths, contents = api_hit
            return _finish(
                _from_fingerprint(
                    fp,
                    suggested_name=suggested,
                    branch=resolved,
                    clone_url=clone_url,
                    paths=paths,
                    contents=contents,
                )
            )

        fp, resolved, paths, contents = _sparse_clone_detect(clone_url=clone_url, branch=br_in)
        return _finish(
            _from_fingerprint(
                fp,
                suggested_name=suggested,
                branch=resolved,
                clone_url=clone_url,
                paths=paths,
                contents=contents,
            )
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_run)
        try:
            return fut.result(timeout=_DETECT_TIMEOUT_SEC)
        except concurrent.futures.TimeoutError as exc:
            raise TimeoutError("仓库探测超时（>5s），请检查网络或手动选择仓库类型") from exc


# 兼容旧单测 / 模块引用
def detect_from_directory_legacy(repo_dir: Path) -> DetectResult:
    fp = detect_from_directory(repo_dir)
    return _from_fingerprint(fp, suggested_name=repo_dir.name, branch="main", clone_url=str(repo_dir))