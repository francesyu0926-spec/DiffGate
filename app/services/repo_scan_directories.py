"""探测后源码根目录树（委托 repo_directory_analyzer）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.repo_detect_fingerprint import FingerprintResult
from app.services.repo_directory_analyzer import run_directory_analysis


def build_directories(
    fp: FingerprintResult,
    *,
    paths: set[str] | None = None,
    contents: dict[str, str] | None = None,
    repo_dir: Path | None = None,
    max_depth: int = 3,
) -> list[dict[str, Any]]:
    del fp  # 目录树由路径索引驱动；指纹仍由 repo_detect 合并
    analyzed = run_directory_analysis(
        paths=paths, contents=contents, repo_dir=repo_dir, max_depth=max_depth
    )
    return list(analyzed.get("directories") or [])


def build_scan_directory_options(
    fp: FingerprintResult,
    *,
    paths: set[str] | None = None,
    contents: dict[str, str] | None = None,
    repo_dir: Path | None = None,
    max_depth: int = 3,
) -> list[dict[str, Any]]:
    return [
        {"path": d["path"], "recommended": d.get("is_recommended")}
        for d in build_directories(
            fp, paths=paths, contents=contents, repo_dir=repo_dir, max_depth=max_depth
        )
    ]