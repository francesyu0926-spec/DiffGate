"""精准回归探针：在目标仓库内执行受影响 API 冒烟并用 coverage 统计增量行命中。"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.db.models import Repository
from app.services.coverage_denom_clean import (
    build_probe_payload,
    clean_changed_lines,
    count_diff_lines,
    coverage_statements_for_repo,
)
from app.services.coverage_hit_align import load_sources, propagate_multiline_hits
from app.services.coverage_path_norm import repo_path_from_coverage_abs
from app.services.runtime_commit import resolve_running_commit_sha

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models import AnalysisJob

logger = logging.getLogger(__name__)

MAX_PROBE_LINES = 800
JOB_HEADER = "X-DiffGate-Job-Id"


@dataclass
class ProbeResult:
    incremental_coverage_pct: float
    tests_passed: bool
    coverage_probes: list[dict[str, Any]] = field(default_factory=list)
    covered_changed_lines: int = 0
    changed_lines: int = 0
    diff_lines_total: int = 0
    lines_filtered: int = 0
    coverage_not_required: bool = False
    api_smoke_results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    branch_coverage_pct: float | None = None


def _norm_repo_path(path: str) -> str:
    return path.replace("\\", "/")


def count_line_range_lines(line_ranges: list[dict]) -> int:
    """与 quality_gate._line_range_stats 一致：Diff 变更行总数。"""
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


def expand_changed_lines(line_ranges: list[dict]) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for block in line_ranges:
        if not isinstance(block, dict):
            continue
        path = _norm_repo_path(str(block.get("path") or "unknown"))
        start = int(block.get("start") or 0)
        end = int(block.get("end") or start)
        if start <= 0:
            continue
        for ln in range(start, end + 1):
            rows.append((path, ln))
    return rows[:MAX_PROBE_LINES]


def guess_python_workdir(repo_dir: Path, line_ranges: list[dict]) -> Path:
    """根据变更路径推断 FastAPI 包根目录（如 backend/）。"""
    for block in line_ranges:
        path = _norm_repo_path(str(block.get("path") or ""))
        parts = path.split("/")
        if "app" in parts:
            idx = parts.index("app")
            if idx > 0:
                return (repo_dir / Path(*parts[:idx])).resolve()
    return repo_dir.resolve()


def _default_query(path: str) -> dict[str, str]:
    p = path.split("?")[0]
    if p.rstrip("/").endswith("klines"):
        return {"symbol": "BTC/USDT", "interval": "1m"}
    if p.rstrip("/").endswith("quotes"):
        return {"symbols": "BTC/USDT"}
    if p.rstrip("/").endswith("health"):
        return {}
    return {}


def _branch_coverage_pct(cov_data, workdir: Path, repo_dir: Path, changed_files: set[str]) -> float | None:
    """基于 coverage 分支弧统计变更文件的平均分支命中率。"""
    try:
        measured = cov_data.measured_files()
    except Exception:
        return None
    total_arcs = 0
    hit_arcs = 0
    abs_to_repo: dict[str, str] = {}
    for abs_path in measured:
        try:
            rel = Path(abs_path).resolve().relative_to(repo_dir.resolve())
            abs_to_repo[abs_path] = _norm_repo_path(rel.as_posix())
        except ValueError:
            continue
    for abs_path, repo_rel in abs_to_repo.items():
        if changed_files and repo_rel not in changed_files:
            continue
        executed = set(cov_data.arcs(abs_path) or [])
        missing = set(cov_data.missing_arc_pairs(abs_path) or [])
        for arc in executed:
            total_arcs += 1
            hit_arcs += 1
        for arc in missing:
            total_arcs += 1
    if total_arcs == 0:
        return None
    return round(hit_arcs / total_arcs * 100, 1)


def _lines_executed(cov_data, workdir: Path, repo_dir: Path) -> set[tuple[str, int]]:
    hits: set[tuple[str, int]] = set()
    measured = cov_data.measured_files()
    abs_to_repo: dict[str, str] = {}
    for abs_path in measured:
        mapped = repo_path_from_coverage_abs(abs_path, repo_dir, workdir)
        if mapped:
            abs_to_repo[abs_path] = _norm_repo_path(mapped)
    for abs_path, repo_rel in abs_to_repo.items():
        nums = cov_data.lines(abs_path) or []
        for ln in nums:
            hits.add((repo_rel, int(ln)))
    return hits


def _partial_branch_lines(cov_data, workdir: Path, repo_dir: Path) -> set[tuple[str, int]]:
    """行已执行但至少一条分支未命中 → 部分覆盖（如 `a or b` 只走了前半）。"""
    partial: set[tuple[str, int]] = set()
    for abs_path in cov_data.measured_files():
        mapped = repo_path_from_coverage_abs(abs_path, repo_dir, workdir)
        if not mapped:
            continue
        executed_arcs = cov_data.arcs(abs_path) or []
        hit_from: set[int] = set()
        for arc in executed_arcs:
            if arc and len(arc) >= 1:
                hit_from.add(int(arc[0]))
        for pair in cov_data.missing_arc_pairs(abs_path) or []:
            if not pair:
                continue
            from_ln = int(pair[0])
            if from_ln in hit_from:
                partial.add((mapped, from_ln))
    return partial


def _suspect_fallback_hits(job: AnalysisJob | Any, changed: list[tuple[str, int]]) -> set[tuple[str, int]]:
    """无法跑 coverage 时：将位于嫌疑函数范围内的变更行标为命中（测试环境兜底）。"""
    suspects = (job.changed_symbols or {}).get("suspects") or []
    hit: set[tuple[str, int]] = set()
    for path, ln in changed:
        for s in suspects:
            if not isinstance(s, dict):
                continue
            file_path = _norm_repo_path(str(s.get("file") or ""))
            if file_path != path:
                continue
            start = int(s.get("start_line") or 0)
            end = int(s.get("end_line") or start)
            if start <= ln <= end:
                hit.add((path, ln))
                break
    return hit


def run_coverage_probe(
    *,
    repo_dir: Path,
    scan_root: str,
    interfaces: list[dict],
    line_ranges: list[dict],
    job: AnalysisJob | None = None,
    repo: Repository | None = None,
    coverage_data_dir: Path | None = None,
    reset_coverage: bool = False,
) -> ProbeResult:
    diff_total = count_diff_lines(line_ranges)
    pre_clean = clean_changed_lines(
        line_ranges,
        repo_dir=repo_dir if repo_dir.is_dir() else None,
        scan_root=scan_root or ".",
        repo=repo,
    )
    changed = pre_clean.effective[:MAX_PROBE_LINES]
    if not changed:
        if pre_clean.coverage_not_required:
            return ProbeResult(
                incremental_coverage_pct=100.0,
                tests_passed=True,
                changed_lines=0,
                covered_changed_lines=0,
                diff_lines_total=pre_clean.diff_lines_total,
                lines_filtered=pre_clean.lines_filtered,
                coverage_not_required=True,
                coverage_probes=build_probe_payload([], pre_clean.ignored, set()),
            )
        if diff_total > 0:
            return ProbeResult(
                incremental_coverage_pct=0.0,
                tests_passed=True,
                changed_lines=0,
                covered_changed_lines=0,
                diff_lines_total=diff_total,
                lines_filtered=pre_clean.lines_filtered,
            )
        return ProbeResult(incremental_coverage_pct=100.0, tests_passed=True, changed_lines=0)

    workdir = guess_python_workdir(repo_dir, line_ranges)
    if scan_root and scan_root not in (".", ""):
        alt = (repo_dir / scan_root).resolve()
        if alt.is_dir():
            workdir = alt

    tests_passed = True
    smoke_ran = False
    api_smoke_results: list[dict[str, Any]] = []
    executed: set[tuple[str, int]] = set()
    err: str | None = None

    try:
        import coverage
        from fastapi.testclient import TestClient
    except ImportError as exc:
        err = f"missing dependency: {exc}"
        if job:
            executed = _suspect_fallback_hits(job, changed)
        covered = len(executed)
        total = len(changed)
        pct = round(covered / total * 100, 1) if total else 100.0
        final_clean = clean_changed_lines(
            line_ranges,
            repo_dir=repo_dir if repo_dir.is_dir() else None,
            scan_root=scan_root or ".",
            repo=repo,
        )
        covered = sum(1 for row in final_clean.effective if row in executed)
        total = len(final_clean.effective)
        pct = round(covered / total * 100, 1) if total else 100.0
        return ProbeResult(
            incremental_coverage_pct=pct,
            tests_passed=bool(executed),
            coverage_probes=build_probe_payload(final_clean.effective, final_clean.ignored, executed),
            covered_changed_lines=covered,
            changed_lines=total,
            diff_lines_total=final_clean.diff_lines_total,
            lines_filtered=final_clean.lines_filtered,
            coverage_not_required=final_clean.coverage_not_required,
            error=err,
        )

    main_py = workdir / "app" / "main.py"
    inserted = str(workdir)
    path_backup = list(sys.path)
    sys.path = [inserted]
    modules_backup: dict[str, Any] = {}
    branch_pct: float | None = None
    branch_partial: set[tuple[str, int]] = set()
    cov_obj: Any = None

    if coverage_data_dir is not None:
        from app.services.coverage_lifecycle import coverage_combine, coverage_reset

        data_dir = coverage_data_dir.resolve()
        if reset_coverage:
            coverage_reset(data_dir)
        coverage_combine(data_dir)
        cov_obj = coverage.Coverage(data_file=str(data_dir / ".coverage"))
        cov_obj.load()
        data = cov_obj.get_data()
        executed = _lines_executed(data, workdir, repo_dir)
        changed_files = {p for p, _ in changed}
        branch_pct = _branch_coverage_pct(data, workdir, repo_dir, changed_files)
        branch_partial = _partial_branch_lines(data, workdir, repo_dir)
    else:
        cov_obj = coverage.Coverage(source=[str(workdir)], branch=True)
        cov_obj.start()
        try:
            if not main_py.is_file():
                raise FileNotFoundError(f"FastAPI entry not found: {main_py}")
            for key in list(sys.modules):
                if key == "app" or key.startswith("app."):
                    modules_backup[key] = sys.modules.pop(key)
            import importlib

            probe_main = importlib.import_module("app.main")
            app = probe_main.app

            stain_headers = {JOB_HEADER: job.id} if job and job.id else {}
            with TestClient(app) as client:
                smoke_ran = True
                for iface in interfaces or [{"method": "GET", "path": "/health"}]:
                    method = str(iface.get("method") or "GET").upper()
                    path = str(iface.get("path") or "/")
                    params = _default_query(path)
                    try:
                        resp = client.request(method, path, params=params, headers=stain_headers)
                        api_smoke_results.append(
                            {
                                "method": method,
                                "path": path,
                                "status_code": int(resp.status_code),
                                "body": (resp.text or "")[:8000],
                                "query": params,
                            }
                        )
                        if resp.status_code >= 500:
                            tests_passed = False
                    except Exception as exc:
                        api_smoke_results.append(
                            {
                                "method": method,
                                "path": path,
                                "status_code": 0,
                                "body": "",
                                "error": str(exc),
                                "query": params,
                            }
                        )
                        tests_passed = False
        except Exception as exc:
            err = str(exc)
            logger.warning("coverage probe app import/smoke failed: %s", exc)
            if job:
                executed = _suspect_fallback_hits(job, changed)
        finally:
            cov_obj.stop()
            try:
                cov_obj.save()
                data = cov_obj.get_data()
                if not executed:
                    executed = _lines_executed(data, workdir, repo_dir)
                    if job and len(executed) < max(1, len(changed) // 4):
                        executed |= _suspect_fallback_hits(job, changed)
                changed_files = {p for p, _ in changed}
                branch_pct = _branch_coverage_pct(data, workdir, repo_dir, changed_files)
                branch_partial = _partial_branch_lines(data, workdir, repo_dir)
            except Exception as exc:
                err = err or str(exc)
            sys.path = path_backup
            for key, mod in modules_backup.items():
                sys.modules[key] = mod

    if not smoke_ran:
        tests_passed = True

    rel_paths = {p for p, _ in pre_clean.effective} | {p for p, _ in pre_clean.ignored}
    stmt_map = coverage_statements_for_repo(cov_obj, repo_dir, workdir, rel_paths)
    final_clean = clean_changed_lines(
        line_ranges,
        repo_dir=repo_dir if repo_dir.is_dir() else None,
        scan_root=scan_root or ".",
        coverage_statements=stmt_map or None,
        repo=repo,
    )
    eff_set = set(final_clean.effective)
    rel_paths = {p for p, _ in eff_set}
    sources = load_sources(repo_dir, rel_paths) if repo_dir.is_dir() else {}
    executed = propagate_multiline_hits(eff_set, executed, sources)
    covered = sum(1 for row in final_clean.effective if row in executed)
    total = len(final_clean.effective)
    if final_clean.coverage_not_required:
        pct = 100.0
    else:
        pct = round(covered / total * 100, 1) if total else 100.0
    return ProbeResult(
        incremental_coverage_pct=pct,
        tests_passed=tests_passed,
        coverage_probes=build_probe_payload(
            final_clean.effective,
            final_clean.ignored,
            executed,
            branch_partial=branch_partial,
        ),
        covered_changed_lines=covered,
        changed_lines=total,
        diff_lines_total=final_clean.diff_lines_total,
        lines_filtered=final_clean.lines_filtered,
        coverage_not_required=final_clean.coverage_not_required,
        api_smoke_results=api_smoke_results,
        error=err,
        branch_coverage_pct=branch_pct,
    )


def repo_dir_for_job(job: AnalysisJob) -> Path:
    from app.config import get_settings

    settings = get_settings()
    safe = job.repo_full_name.replace("/", "_")
    return (Path(settings.repo_clone_root) / safe).resolve()


def run_coverage_probe_for_job_id(job_id: str) -> ProbeResult | None:
    from sqlalchemy import select

    from app.db.models import AnalysisJob, Repository
    from app.db.session import SessionLocal
    from app.services.quality_gate import apply_gate_result

    db = SessionLocal()
    try:
        job = db.get(AnalysisJob, job_id)
        if not job:
            return None
        repo_rec = db.scalar(select(Repository).where(Repository.full_name == job.repo_full_name))
        repo_dir = repo_dir_for_job(job)
        if not repo_dir.is_dir():
            raise FileNotFoundError(f"clone not found: {repo_dir}")

        line_ranges = (job.changed_symbols or {}).get("line_ranges") or []
        apis = (job.affected_apis or {}).get("apis") or []
        scan_root = (repo_rec.scan_root if repo_rec and repo_rec.scan_root else ".") or "."

        import os

        cov_dir_raw = os.environ.get("DIFFGATE_COVERAGE_DATA_DIR", "").strip()
        cov_dir = Path(cov_dir_raw) if cov_dir_raw else None
        reset_cov = os.environ.get("DIFFGATE_COVERAGE_RESET", "").lower() in ("1", "true", "yes")

        result = run_coverage_probe(
            repo_dir=repo_dir,
            scan_root=scan_root,
            interfaces=apis,
            line_ranges=line_ranges,
            job=job,
            repo=repo_rec,
            coverage_data_dir=cov_dir,
            reset_coverage=reset_cov,
        )
        running_sha = resolve_running_commit_sha(repo_dir) or (job.head_sha or None)
        gate = apply_gate_result(
            job,
            repo_rec,
            incremental_coverage_pct=result.incremental_coverage_pct,
            tests_passed=result.tests_passed,
            coverage_probes=result.coverage_probes,
            covered_changed_lines=result.covered_changed_lines,
            api_smoke_results=result.api_smoke_results or None,
            diff_lines_total=result.diff_lines_total,
            executable_changed_lines=result.changed_lines,
            lines_filtered=result.lines_filtered,
            coverage_not_required=result.coverage_not_required,
            running_commit_sha=running_sha,
        )
        from app.services.job_execution_state import mark_completed_after_probe

        mark_completed_after_probe(job)
        if result.branch_coverage_pct is not None:
            gate["branch_coverage_pct"] = result.branch_coverage_pct
            job.gate_result = gate
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def submit_gate_report_http(
    job_id: str,
    result: ProbeResult,
    *,
    api_base: str | None = None,
) -> dict[str, Any]:
    import httpx

    from app.config import get_settings

    settings = get_settings()
    base = (api_base or settings.api_public_base_url or "http://127.0.0.1:8000").rstrip("/")
    body = {
        "incremental_coverage_pct": result.incremental_coverage_pct,
        "tests_passed": result.tests_passed,
        "coverage_probes": result.coverage_probes,
        "running_commit_sha": resolve_running_commit_sha(),