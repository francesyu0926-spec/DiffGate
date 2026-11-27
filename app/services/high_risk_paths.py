"""高危黑白名单、加权计数与明细披露。"""

from __future__ import annotations

import fnmatch
import re
from typing import Any

from app.db.models import AnalysisJob, Repository

HIGH_RISK_API_THRESHOLD = 5
HIGH_RISK_SYMBOL_THRESHOLD = 8
LEVEL_CORE = "核心高危"
LEVEL_THRESHOLD = "数量超限"


def normalize_patterns(raw: list | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for row in raw:
        if isinstance(row, str):
            p = row.strip().replace("\\", "/")
        elif isinstance(row, dict):
            p = str(row.get("pattern") or row.get("path") or "").strip().replace("\\", "/")
        else:
            continue
        if p:
            out.append(p)
    return out


def changed_paths_from_job(job: AnalysisJob) -> list[str]:
    suspects = getattr(job, "changed_symbols", None) or {}
    paths: list[str] = []
    for lr in suspects.get("line_ranges") or []:
        if not isinstance(lr, dict):
            continue
        p = lr.get("path")
        if p:
            paths.append(str(p).replace("\\", "/"))
    for sym in suspects.get("suspects") or []:
        if isinstance(sym, dict) and sym.get("file"):
            paths.append(str(sym["file"]).replace("\\", "/"))
    return list(dict.fromkeys(paths))


def _regex_from_glob(pattern: str) -> re.Pattern[str] | None:
    if pattern.startswith("^") or pattern.endswith("$") or "(?:" in pattern:
        try:
            return re.compile(pattern)
        except re.error:
            return None
    globs = ("*", "?", "[")
    if not any(g in pattern for g in globs):
        pattern = f"**/{pattern}" if "/" not in pattern else pattern
    regex = fnmatch.translate(pattern)
    try:
        return re.compile(regex, re.IGNORECASE)
    except re.error:
        return None


def path_matches_pattern(path: str, pattern: str) -> bool:
    p = path.replace("\\", "/").lstrip("/")
    pat = pattern.replace("\\", "/")
    if p.startswith(pat) or f"/{pat}" in f"/{p}":
        return True
    rx = _regex_from_glob(pat)
    if rx and rx.search(p):
        return True
    return fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p, f"**/{pat}")


def path_matches_any(path: str, patterns: list[str]) -> str | None:
    for pat in patterns:
        if path_matches_pattern(path, pat):
            return pat
    return None


def high_risk_patterns_for_repo(repo: Repository | None) -> list[str]:
    if not repo:
        return []
    raw = getattr(repo, "high_risk_paths", None)
    if raw is None:
        return []
    return normalize_patterns(raw)


def low_risk_patterns_for_repo(repo: Repository | None) -> list[str]:
    if not repo:
        return []
    raw = getattr(repo, "low_risk_paths", None)
    if raw is None:
        return []
    return normalize_patterns(raw)


def is_ignored_low_risk_path(path: str, repo: Repository | None) -> bool:
    patterns = low_risk_patterns_for_repo(repo)
    if not patterns:
        return False
    return path_matches_any(path, patterns) is not None


def repo_risk_thresholds(repo: Repository | None) -> tuple[int, int]:
    api_th = HIGH_RISK_API_THRESHOLD
    sym_th = HIGH_RISK_SYMBOL_THRESHOLD
    if repo:
        if getattr(repo, "high_risk_api_threshold", None) is not None:
            api_th = int(repo.high_risk_api_threshold)
        if getattr(repo, "high_risk_symbol_threshold", None) is not None:
            sym_th = int(repo.high_risk_symbol_threshold)
    return api_th, sym_th


def risk_weighted_counts(job: AnalysisJob, repo: Repository | None) -> tuple[int, int, int, int]:
    """返回 (加权API, 加权符号, 原始API, 原始符号)。低危白名单不计入阈值统计。"""
    apis = (getattr(job, "affected_apis", None) or {}).get("apis") or []
    raw_api = int((getattr(job, "affected_apis", None) or {}).get("count") or len(apis))
    weighted_api = 0
    for api in apis:
        if not isinstance(api, dict):
            continue
        f = str(api.get("file") or "")
        if f and is_ignored_low_risk_path(f, repo):
            continue
        weighted_api += 1
    if not apis:
        weighted_api = raw_api

    suspects = getattr(job, "changed_symbols", None) or {}
    symbols = suspects.get("symbols") or []
    raw_sym = len(symbols) if symbols else len(changed_paths_from_job(job))

    sym_files: dict[str, str] = {}
    for sym in suspects.get("suspects") or []:
        if not isinstance(sym, dict):
            continue
        qn = sym.get("qualified_name") or sym.get("name")
        if qn:
            sym_files[str(qn)] = str(sym.get("file") or sym.get("file_path") or "")

    weighted_sym = 0
    if symbols:
        for name in symbols:
            fp = sym_files.get(str(name), "")
            if fp and is_ignored_low_risk_path(fp, repo):
                continue
            weighted_sym += 1
    else:
        for path in changed_paths_from_job(job):
            if not is_ignored_low_risk_path(path, repo):
                weighted_sym += 1

    return weighted_api, weighted_sym, raw_api, raw_sym


def core_path_hits(changed_paths: list[str], patterns: list[str]) -> list[str]:
    hits: list[str] = []
    for path in changed_paths:
        for pat in patterns:
            if path_matches_pattern(path, pat):
                hits.append(pat)
                break
    return list(dict.fromkeys(hits))


def evaluate_high_risk(
    job: AnalysisJob,
    repo: Repository | None,
    *,
    api_count: int,
    symbol_count: int,
) -> tuple[bool, dict[str, Any]]:
    patterns = high_risk_patterns_for_repo(repo)
    paths = changed_paths_from_job(job)
    core_hits = core_path_hits(paths, patterns) if patterns else []

    api_th, sym_th = repo_risk_thresholds(repo)
    path_triggered = bool(core_hits)
    threshold_triggered = api_count >= api_th and symbol_count >= sym_th
    should_block = path_triggered or threshold_triggered

    mode = "none"
    if path_triggered and threshold_triggered:
        mode = "path_and_threshold"
    elif path_triggered:
        mode = "core_path"
    elif threshold_triggered:
        mode = "threshold"

    return should_block, {
        "mode": mode,
        "path_triggered": path_triggered,
        "threshold_triggered": threshold_triggered,
        "core_paths": core_hits,
        "api_threshold": api_th,
        "symbol_threshold": sym_th,
        "api_impact": api_count,
        "symbol_count": symbol_count,
    }


def build_high_risk_details(
    job: AnalysisJob,
    repo: Repository | None,
    hr_meta: dict[str, Any],
) -> dict[str, Any]:
    triggered_by: list[str] = []
    if hr_meta.get("path_triggered"):
        triggered_by.append("path_rule")
    if hr_meta.get("threshold_triggered"):
        triggered_by.append("threshold")

    patterns = high_risk_patterns_for_repo(repo)
    paths = changed_paths_from_job(job)
    path_to_pattern: dict[str, str] = {}
    for path in paths:
        hit = path_matches_any(path, patterns)
        if hit:
            path_to_pattern[path] = hit

    suspects = getattr(job, "changed_symbols", None) or {}
    seen: set[tuple[str, str | None]] = set()
    matched_modules: list[dict[str, Any]] = []

    for sym in suspects.get("suspects") or []:
        if not isinstance(sym, dict):
            continue
        file_path = str(sym.get("file") or sym.get("file_path") or "").replace("\\", "/")
        qn = sym.get("qualified_name") or sym.get("name")
        pat = path_to_pattern.get(file_path)
        if pat:
            key = (file_path, str(qn) if qn else None)
            if key in seen:
                continue
            seen.add(key)
            matched_modules.append(
                {
                    "file": file_path,
                    "symbol": qn,
                    "level": LEVEL_CORE,
                    "reason": f"命中高危路径 {pat}",
                }
            )

    for path, pat in path_to_pattern.items():
        if any(m.get("file") == path for m in matched_modules):
            continue
        matched_modules.append(
            {
                "file": path,
                "symbol": None,
                "level": LEVEL_CORE,
                "reason": f"命中高危路径 {pat}",
            }
        )

    if hr_meta.get("threshold_triggered"):
        api_th = int(hr_meta.get("api_threshold") or HIGH_RISK_API_THRESHOLD)
        sym_th = int(hr_meta.get("symbol_threshold") or HIGH_RISK_SYMBOL_THRESHOLD)
        matched_modules.append(
            {
                "file": None,
                "symbol": None,
                "level": LEVEL_THRESHOLD,
                "reason": (
                    f"影响 API {hr_meta.get('api_impact')} 个（≥{api_th}）"
                    f"且符号 {hr_meta.get('symbol_count')} 个（≥{sym_th}）"
                ),
            }
        )

    return {
        "triggered_by": triggered_by,
        "api_count": int(hr_meta.get("api_impact") or 0),
        "api_threshold": int(hr_meta.get("api_threshold") or HIGH_RISK_API_THRESHOLD),
        "symbol_count": int(hr_meta.get("symbol_count") or 0),
        "symbol_threshold": int(hr_meta.get("symbol_threshold") or HIGH_RISK_SYMBOL_THRESHOLD),
        "matched_modules": matched_modules[:40],
    }