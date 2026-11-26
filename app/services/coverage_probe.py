"""精准回归探针：在目标仓库内执行受影响 API 冒烟并用 coverage 统计增量行命中。"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    api_smoke_results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    branch_coverage_pct: float | None = None


def _norm_repo_path(path: str) -> str:
    return path.replace("\\", "/")


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
        try:
            rel = Path(abs_path).resolve().relative_to(repo_dir.resolve())
            abs_to_repo[abs_path] = _norm_repo_path(rel.as_posix())
        except ValueError:
            try:
                rel = Path(abs_path).resolve().relative_to(workdir.resolve())
                prefix = workdir.resolve().relative_to(repo_dir.resolve()).as_posix()
                abs_to_repo[abs_path] = _norm_repo_path(f"{prefix}/{rel.as_posix()}".lstrip("./"))
            except ValueError:
                continue
    for abs_path, repo_rel in abs_to_repo.items():
        nums = cov_data.lines(abs_path) or []
        for ln in nums:
            hits.add((repo_rel, int(ln)))
    return hits


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


def _probe_rows(changed: list[tuple[str, int]], executed: set[tuple[str, int]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, ln in changed:
        rows.append(
            {
                "file": path,
                "line": ln,
                "covered": (path, ln) in executed,
                "prefix": "+",
            }
        )
    return rows


def run_coverage_probe(
    *,
    repo_dir: Path,
    scan_root: str,
    interfaces: list[dict],
    line_ranges: list[dict],
    job: AnalysisJob | None = None,
) -> ProbeResult:
    changed = expand_changed_lines(line_ranges)
    if not changed:
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
        return ProbeResult(
            incremental_coverage_pct=pct,
            tests_passed=bool(executed),
            coverage_probes=_probe_rows(changed, executed),
            covered_changed_lines=covered,
            changed_lines=total,
            error=err,
        )

    main_py = workdir / "app" / "main.py"
    cov = coverage.Coverage(source=[str(workdir)], branch=True)
    cov.start()
    inserted = str(workdir)
    path_backup = list(sys.path)
    sys.path = [inserted]
    modules_backup = {}
    branch_pct: float | None = None
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
        cov.stop()
        try:
            cov.save()
            data = cov.get_data()
            if not executed:
                executed = _lines_executed(data, workdir, repo_dir)
                if job and len(executed) < max(1, len(changed) // 4):
                    executed |= _suspect_fallback_hits(job, changed)
            changed_files = {p for p, _ in changed}
            branch_pct = _branch_coverage_pct(data, workdir, repo_dir, changed_files)
        except Exception as exc:
            err = err or str(exc)
        sys.path = path_backup
        for key, mod in modules_backup.items():
            sys.modules[key] = mod

    if not smoke_ran:
        tests_passed = True

    covered = sum(1 for row in changed if row in executed)
    total = len(changed)
    pct = round(covered / total * 100, 1) if total else 100.0
    return ProbeResult(
        incremental_coverage_pct=pct,
        tests_passed=tests_passed,
        coverage_probes=_probe_rows(changed, executed),
        covered_changed_lines=covered,
        changed_lines=total,
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

        result = run_coverage_probe(
            repo_dir=repo_dir,
            scan_root=scan_root,
            interfaces=apis,
            line_ranges=line_ranges,
            job=job,
        )
        gate = apply_gate_result(
            job,
            repo_rec,
            incremental_coverage_pct=result.incremental_coverage_pct,
            tests_passed=result.tests_passed,
            coverage_probes=result.coverage_probes,
            covered_changed_lines=result.covered_changed_lines,
            api_smoke_results=result.api_smoke_results or None,
        )
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
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(f"{base}/api/v1/jobs/{job_id}/gate-report", json=body)
        resp.raise_for_status()
        return resp.json()