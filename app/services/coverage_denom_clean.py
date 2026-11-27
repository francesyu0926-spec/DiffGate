"""增量覆盖率分母清洗：文件/目录过滤、Python 非可执行行、coverage statements 对齐。"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.db.models import Repository
from app.services.high_risk_paths import is_ignored_low_risk_path
from app.services.coverage_circuit_breaker import count_added_lines_per_file, ultra_large_skip_reason
from app.adapters.registry import normalize_repo_type
from app.services.go_executable_lines import is_go_executable_line, is_go_test_or_generated
from app.services.java_executable_lines import is_java_executable_line, is_java_test_path
from app.services.python_executable_lines import effective_executable_lines_from_path

_NON_CODE_SUFFIXES = (
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".sql",
    ".sh",
    ".bat",
    ".ps1",
    ".csv",
    ".xml",
    ".html",
    ".css",
    ".scss",
    ".lock",
)

_SKIP_DIR_NAMES = frozenset({"tests", "test", "scripts", "migrations", "__pycache__"})


@dataclass
class DenomCleanResult:
    effective: list[tuple[str, int]] = field(default_factory=list)
    ignored: list[tuple[str, int, str]] = field(default_factory=list)
    diff_lines_total: int = 0
    executable_changed_lines: int = 0
    lines_filtered: int = 0
    ultra_large_files: list[str] = field(default_factory=list)

    @property
    def coverage_not_required(self) -> bool:
        return self.diff_lines_total > 0 and self.executable_changed_lines == 0


def _norm_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def count_diff_lines(line_ranges: Iterable[dict]) -> int:
    total = 0
    for block in line_ranges:
        if not isinstance(block, dict):
            continue
        start = int(block.get("start") or 0)
        end = int(block.get("end") or start)
        if start <= 0:
            continue
        total += max(0, end - start + 1)
    return total


def iter_diff_line_pairs(line_ranges: Iterable[dict]) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for block in line_ranges:
        if not isinstance(block, dict):
            continue
        path = _norm_path(str(block.get("path") or "unknown"))
        start = int(block.get("start") or 0)
        end = int(block.get("end") or start)
        if start <= 0:
            continue
        for ln in range(start, end + 1):
            rows.append((path, ln))
    return rows


def level1_path_reason(
    path: str,
    scan_root: str = ".",
    repo: Repository | None = None,
) -> str | None:
    norm = _norm_path(path)
    if repo and is_ignored_low_risk_path(norm, repo):
        return "low_risk_whitelist"
    root = (scan_root or ".").strip().rstrip("/")
    if root and root not in (".", ""):
        if not (norm == root or norm.startswith(f"{root}/")):
            return "outside_scan_root"
    name = norm.rsplit("/", 1)[-1].lower()
    if name.startswith(".env"):
        return "config_file"
    for suf in _NON_CODE_SUFFIXES:
        if name.endswith(suf):
            return "non_code_file"
    for part in norm.split("/"):
        if part in _SKIP_DIR_NAMES:
            return "test_or_script_dir"
    if fnmatch.fnmatch(name, "test_*.py") or fnmatch.fnmatch(name, "*_test.py"):
        return "test_file"
    if is_java_test_path(norm):
        return "java_test_source"
    if is_go_test_or_generated(norm):
        return "go_test_or_generated"
    return None


def clean_changed_lines(
    line_ranges: list[dict],
    *,
    repo_dir: Path | None,
    scan_root: str = ".",
    coverage_statements: dict[str, set[int]] | None = None,
    repo: Repository | None = None,
) -> DenomCleanResult:
    """对 Diff 展开行做 L1–L3 清洗，得到有效可执行变更行集合。"""
    pairs = iter_diff_line_pairs(line_ranges)
    diff_total = count_diff_lines(line_ranges)
    added_per_file = count_added_lines_per_file(line_ranges)
    ultra_paths: set[str] = set()
    for fpath, added in added_per_file.items():
        if ultra_large_skip_reason(fpath, repo_dir, added):
            ultra_paths.add(fpath)
    py_cache: dict[str, set[int]] = {}
    java_cache: dict[str, set[int]] = {}
    go_cache: dict[str, set[int]] = {}
    rtype = normalize_repo_type(getattr(repo, "repo_type", None) if repo else None)
    effective: list[tuple[str, int]] = []
    ignored: list[tuple[str, int, str]] = []

    for path, ln in pairs:
        reason = level1_path_reason(path, scan_root, repo)
        if reason:
            ignored.append((path, ln, reason))
            continue

        if path in ultra_paths:
            reason = ultra_large_skip_reason(path, repo_dir, added_per_file.get(path, 0)) or "ultra_large"
            ignored.append((path, ln, reason))
            continue

        is_py = path.lower().endswith(".py")
        if is_py and repo_dir is not None:
            if path not in py_cache:
                py_cache[path] = effective_executable_lines_from_path(repo_dir / path)
            if ln not in py_cache[path]:
                ignored.append((path, ln, "non_executable"))
                continue

        is_java = path.lower().endswith(".java")
        is_go = path.lower().endswith(".go")
        if is_go and repo_dir is not None and rtype == "backend_go":
            if path not in go_cache:
                fp = repo_dir / path
                if fp.is_file():
                    go_cache[path] = {
                        idx
                        for idx, line in enumerate(fp.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
                        if is_go_executable_line(line)
                    }
                else:
                    go_cache[path] = set()
            if ln not in go_cache[path]:
                ignored.append((path, ln, "non_executable"))
                continue

        if is_java and repo_dir is not None and rtype == "backend_java":
            if path not in java_cache:
                fp = repo_dir / path
                if fp.is_file():
                    java_cache[path] = {
                        idx
                        for idx, line in enumerate(fp.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
                        if is_java_executable_line(line)
                    }
                else:
                    java_cache[path] = set()
            if ln not in java_cache[path]:
                ignored.append((path, ln, "non_executable"))
                continue

        if coverage_statements is not None:
            stmts = coverage_statements.get(path)
            if stmts is not None and ln not in stmts:
                ignored.append((path, ln, "coverage_non_statement"))
                continue

        effective.append((path, ln))

    exec_n = len(effective)
    return DenomCleanResult(
        effective=effective,
        ignored=ignored,
        diff_lines_total=diff_total,
        executable_changed_lines=exec_n,
        lines_filtered=max(0, diff_total - exec_n),
        ultra_large_files=sorted(ultra_paths),
    )


def coverage_statements_for_repo(
    cov: Any,
    repo_dir: Path,
    workdir: Path,
    rel_paths: set[str],
) -> dict[str, set[int]]:
    """Level 3：coverage.py analysis2 可执行语句行号（按仓库相对路径）。"""
    out: dict[str, set[int]] = {}
    if not hasattr(cov, "analysis2"):
        return out
    repo_dir = repo_dir.resolve()
    workdir = workdir.resolve()
    for rel in rel_paths:
        if not rel.lower().endswith(".py"):
            continue
        candidates = [repo_dir / rel, workdir / rel]
        if "/" in rel:
            tail = rel.split("/", 1)[-1]
            candidates.append(workdir / tail)
        for abs_path in candidates:
            try:
                resolved = abs_path.resolve()
            except OSError:
                continue
            if not resolved.is_file():
                continue
            try:
                _fn, executable, _excl, missing, *_rest = cov.analysis2(str(resolved))
                stmt = set(int(x) for x in executable) | set(int(x) for x in (missing or ()))
                out[rel] = stmt
                break
            except Exception:
                continue
    return out


def build_probe_payload(
    effective: list[tuple[str, int]],
    ignored: list[tuple[str, int, str]],
    executed: set[tuple[str, int]],
    *,
    branch_partial: set[tuple[str, int]] | None = None,
) -> list[dict[str, Any]]:
    partial = branch_partial or set()
    rows: list[dict[str, Any]] = []
    for path, ln in effective:
        hit = (path, ln) in executed
        row: dict[str, Any] = {
            "file": path,
            "line": ln,
            "covered": hit,
            "prefix": "+",
            "ignored": False,
        }
        if hit and (path, ln) in partial:
            row["branch_partial"] = True
        rows.append(row)
    for path, ln, reason in ignored:
        rows.append(
            {
                "file": path,
                "line": ln,
                "covered": None,
                "prefix": "+",
                "ignored": True,
                "filter_reason": reason,
            }
        )
    return rows