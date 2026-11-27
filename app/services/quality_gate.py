"""质量门禁：基于 AnalysisJob 真实字段 + 可选 CI 覆盖率回传。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db.models import AnalysisJob, Repository
from app.services.gate_path_rules import effective_threshold, override_allowed_for_job
from app.services.high_risk_paths import (
    build_high_risk_details,
    changed_paths_from_job,
    evaluate_high_risk,
    high_risk_patterns_for_repo,
    risk_weighted_counts,
)
from app.utils.time_format import as_utc_iso

REASON_LABELS: dict[str, str] = {
    "incremental_coverage_low": "增量覆盖率不足",
    "analysis_failed": "分析任务失败",
    "core_api_regression": "核心接口回归失败",
    "high_risk_unreviewed": "高危模块未评审",
    "pending_coverage": "待覆盖率回传",
    "breaking_contract_change": "破坏性接口契约变更",
}

OVERRIDE_REASON_LABELS: dict[str, str] = {
    "hotfix": "紧急线上 Hotfix 优先发布",
    "branch_unsimulatable": "极端异常分支无法模拟",
    "non_core_reviewed": "非核心逻辑已评审确认无风险",
    "fe_be_coordinated": "前后端协同改造中",
    "other": "其他",
}

HIGH_RISK_API_THRESHOLD = 5
HIGH_RISK_SYMBOL_THRESHOLD = 8


def _top_impacted_apis(job: AnalysisJob, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for api in (job.affected_apis or {}).get("apis") or []:
        if not isinstance(api, dict):
            continue
        rows.append(
            {
                "method": (api.get("method") or "GET").upper(),
                "path": api.get("path") or "/",
                "file": api.get("file"),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _top_changed_symbols(job: AnalysisJob, limit: int = 10) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sym in (job.changed_symbols or {}).get("suspects") or []:
        if not isinstance(sym, dict):
            continue
        qn = sym.get("qualified_name") or sym.get("name")
        if not qn:
            continue
        rows.append(
            {
                "qualified_name": qn,
                "file": sym.get("file") or sym.get("file_path"),
            }
        )
        if len(rows) >= limit:
            break
    if rows:
        return rows
    for name in (job.changed_symbols or {}).get("symbols") or []:
        if not name:
            continue
        rows.append({"qualified_name": str(name), "file": None})
        if len(rows) >= limit:
            break
    return rows


def _failed_smoke_apis(gr: dict[str, Any]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for row in gr.get("api_smoke_results") or []:
        if not isinstance(row, dict):
            continue
        code = int(row.get("status_code") or 0)
        if code >= 400 or row.get("error"):
            failed.append(
                {
                    "method": (row.get("method") or "GET").upper(),
                    "path": row.get("path") or "/",
                    "status_code": code or None,
                    "error": row.get("error"),
                }
            )
    return failed


def build_trigger_detail(
    job: AnalysisJob,
    gr: dict[str, Any],
    *,
    covered_changed_lines: int | None = None,
) -> dict[str, Any] | None:
    code = gr.get("block_reason")
    if gr.get("gate") != "BLOCK" or not code:
        return None

    threshold = int(gr.get("coverage_threshold") or 80)
    api_count = int(gr.get("api_impact") or _api_count(job))
    symbol_count = int(gr.get("symbol_count") or _symbol_count(job))
    apis = _top_impacted_apis(job)
    symbols = _top_changed_symbols(job)
    covered = covered_changed_lines
    if covered is None:
        covered = int(gr.get("covered_changed_lines") or 0)

    if code == "high_risk_unreviewed":
        hr_meta = gr.get("high_risk_meta") or {}
        if hr_meta.get("mode") in ("core_path", "path_and_threshold") and hr_meta.get("core_paths"):
            cores = ", ".join(hr_meta["core_paths"][:4])
            summary = f"变更命中核心高危路径（{cores}），需人工评审后方可放行"
        else:
            api_th = int(hr_meta.get("api_threshold") or HIGH_RISK_API_THRESHOLD)
            sym_th = int(hr_meta.get("symbol_threshold") or HIGH_RISK_SYMBOL_THRESHOLD)
            summary = (
                f"影响 API {api_count} 个（阈值 ≥{api_th}），"
                f"变更符号 {symbol_count} 个（阈值 ≥{sym_th}）"
            )
        return {
            "kind": code,
            "summary": summary,
            "metrics": {
                "api_impact": api_count,
                "api_threshold": int(
                    hr_meta.get("api_threshold") or HIGH_RISK_API_THRESHOLD
                ),
                "symbol_count": symbol_count,
                "symbol_threshold": int(
                    hr_meta.get("symbol_threshold") or HIGH_RISK_SYMBOL_THRESHOLD
                ),
                "core_paths": hr_meta.get("core_paths") or [],
            },
            "high_risk_items": {"apis": apis, "symbols": symbols},
        }

    if code == "incremental_coverage_low":
        cov = float(gr.get("incremental_coverage_pct") or 0)
        changed = int(gr.get("changed_lines") or 0)
        summary = f"增量覆盖率 {cov}% < 门禁基线 {threshold}%"
        if changed > 0:
            summary += f"；变更 {changed} 行，探针命中 {covered} 行"
        return {
            "kind": code,
            "summary": summary,
            "metrics": {
                "incremental_coverage_pct": cov,
                "coverage_threshold": threshold,
                "changed_lines": changed,
                "covered_changed_lines": covered,
            },
            "high_risk_items": {"apis": apis[:6], "symbols": symbols[:6]},
        }

    if code == "core_api_regression":
        failed = _failed_smoke_apis(gr)
        items = failed if failed else apis
        return {
            "kind": code,
            "summary": f"核心接口冒烟未通过（{len(items)} 个待关注）",
            "metrics": {"api_impact": api_count, "failed_smoke_count": len(failed)},
            "high_risk_items": {"apis": items[:8]},
        }

    if code == "analysis_failed":
        return {
            "kind": code,
            "summary": "分析任务失败，未完成影响面与覆盖率评估",
            "metrics": {},
            "high_risk_items": {"symbols": symbols[:6], "apis": apis[:6]},
        }

    label = gr.get("block_reason_label") or REASON_LABELS.get(str(code), str(code))
    return {
        "kind": str(code),
        "summary": str(label),
        "metrics": {"api_impact": api_count, "symbol_count": symbol_count},
        "high_risk_items": {"apis": apis[:6], "symbols": symbols[:6]},
    }


def _line_range_stats(job: AnalysisJob) -> tuple[int, int]:
    suspects = job.changed_symbols or {}
    line_ranges = suspects.get("line_ranges") or []
    files: set[str] = set()
    lines = 0
    for lr in line_ranges:
        if not isinstance(lr, dict):
            continue
        path = lr.get("path")
        if path:
            files.add(path)
        start = int(lr.get("start") or 0)
        end = int(lr.get("end") or start)
        lines += max(0, end - start + 1)
    return len(files), lines


def _api_count(job: AnalysisJob) -> int:
    apis = job.affected_apis or {}
    return int(apis.get("count") or 0)


def _contract_impact(job: AnalysisJob) -> dict[str, Any]:
    aa = job.affected_apis or {}
    cross = aa.get("cross_repo") if isinstance(aa.get("cross_repo"), dict) else {}
    ci = cross.get("contract_impact") if isinstance(cross, dict) else {}
    return ci if isinstance(ci, dict) else {}


def _breaking_contract_hits(job: AnalysisJob) -> list[dict[str, Any]]:
    return [h for h in _contract_impact(job).get("breaking_hits") or [] if isinstance(h, dict)]


def build_breaking_contract_details(job: AnalysisJob) -> dict[str, Any]:
    hits = _breaking_contract_hits(job)
    rows = []
    for h in hits:
        rows.append(
            {
                "backend_api": f"{h.get('method') or ''} {h.get('path') or h.get('api_path') or ''}".strip(),
                "frontend_repo": h.get("frontend_repo"),
                "page_file": h.get("page_file"),
                "change_type": h.get("change_type"),
                "confidence": h.get("confidence"),
            }
        )
    return {
        "triggered_by": "breaking_contract_change",
        "matched_impacts": rows,
        "summary": f"破坏性契约变更 {len(rows)} 项（关联前端调用可确认）",
        "override_hint": (
            "若前端已在关联 MR 中同步移除/修改调用，QA 可选择豁免原因"
            "「前后端协同改造中」一键特批，待前端 MR 合并后索引将自动刷新状态。"
        ),
    }


def _symbol_count(job: AnalysisJob) -> int:
    suspects = job.changed_symbols or {}
    symbols = suspects.get("symbols") or []
    return len(symbols)


def is_zero_impact_job(job: AnalysisJob) -> bool:
    """与前端 JobDetail「零影响 / 自动放行」判定一致。"""
    suspects = job.changed_symbols or {}
    apis = job.affected_apis or {}
    if _api_count(job) > 0:
        return False
    if len(apis.get("apis") or []) > 0:
        return False
    if len(apis.get("call_paths") or []) > 0:
        return False
    if _symbol_count(job) > 0:
        return False
    if len(suspects.get("suspects") or []) > 0:
        return False
    return True


def build_gate_result(
    job: AnalysisJob,
    *,
    threshold: int,
    incremental_coverage_pct: float | None = None,
    tests_passed: bool | None = None,
    override_reason: str | None = None,
    repo: Repository | None = None,
    path_gate_rule: str | None = None,
    allow_override: bool | None = None,
) -> dict[str, Any]:
    changed_files, changed_lines = _line_range_stats(job)
    api_count = _api_count(job)
    symbol_count = _symbol_count(job)
    now = datetime.utcnow().isoformat()

    changed_paths = changed_paths_from_job(job)
    eff_threshold, path_rule = effective_threshold(
        changed_paths,
        repo_rules=getattr(repo, "gate_path_rules", None) if repo else None,
        default_threshold=threshold,
    )

    base: dict[str, Any] = {
        "changed_files": changed_files,
        "changed_lines": changed_lines,
        "api_impact": api_count,
        "symbol_count": symbol_count,
        "coverage_threshold": eff_threshold,
        "evaluated_at": now,
        "incremental_coverage_pct": incremental_coverage_pct,
        "coverage_source": "ci" if incremental_coverage_pct is not None else "pending",
        "tests_passed": tests_passed,
    }
    if path_rule:
        base["path_gate_rule"] = path_rule.path_prefix
        base["allow_override"] = path_rule.allow_override
    elif path_gate_rule:
        base["path_gate_rule"] = path_gate_rule
        if allow_override is not None:
            base["allow_override"] = allow_override
    else:
        base["allow_override"] = override_allowed_for_job(
            changed_paths, getattr(repo, "gate_path_rules", None) if repo else None
        )
    if repo and getattr(repo, "high_risk_paths", None) is not None:
        base["high_risk_paths_configured"] = bool(high_risk_patterns_for_repo(repo))

    if job.status == "failed":
        return {
            **base,
            "gate": "BLOCK",
            "block_reason": "analysis_failed",
            "block_reason_label": REASON_LABELS["analysis_failed"],
        }

    if job.status not in ("completed", "running"):
        return {
            **base,
            "gate": "PENDING",
            "block_reason": None,
            "block_reason_label": None,
        }

    breaking = _breaking_contract_hits(job)
    if breaking:
        ci = _contract_impact(job)
        return {
            **base,
            "gate": "BLOCK",
            "block_reason": "breaking_contract_change",
            "block_reason_label": REASON_LABELS["breaking_contract_change"],
            "cross_repo_impacts": {
                "breaking_hits": breaking,
                "warnings": ci.get("warnings") or [],
                "impacts": ci.get("impacts") or [],
                "perspective": ci.get("perspective"),
            },
            "high_risk_details": build_breaking_contract_details(job),
        }

    if override_reason:
        return {
            **base,
            "gate": "BLOCK",
            "block_reason": override_reason,
            "block_reason_label": REASON_LABELS.get(override_reason, override_reason),
        }

    if is_zero_impact_job(job):
        return {
            **base,
            "gate": "PASS",
            "block_reason": None,
            "block_reason_label": None,
            "coverage_source": "auto_zero_impact",
            "incremental_coverage_pct": incremental_coverage_pct,
        }

    if incremental_coverage_pct is None:
        return {
            **base,
            "gate": "PENDING",
            "block_reason": "pending_coverage",
            "block_reason_label": REASON_LABELS["pending_coverage"],
        }

    cov = float(incremental_coverage_pct)
    if tests_passed is False and api_count > 0:
        return {
            **base,
            "gate": "BLOCK",
            "block_reason": "core_api_regression",
            "block_reason_label": REASON_LABELS["core_api_regression"],
            "incremental_coverage_pct": cov,
            "coverage_source": "ci",
        }

    if cov < eff_threshold:
        return {
            **base,
            "gate": "BLOCK",
            "block_reason": "incremental_coverage_low",
            "block_reason_label": REASON_LABELS["incremental_coverage_low"],
            "incremental_coverage_pct": cov,
            "coverage_source": "ci",
        }

    w_api, w_sym, _, _ = risk_weighted_counts(job, repo)
    high_risk, hr_meta = evaluate_high_risk(
        job, repo, api_count=w_api, symbol_count=w_sym
    )
    base["risk_weighted_api_impact"] = w_api
    base["risk_weighted_symbol_count"] = w_sym
    if high_risk:
        details = build_high_risk_details(job, repo, hr_meta)
        return {
            **base,
            "gate": "BLOCK",
            "block_reason": "high_risk_unreviewed",
            "block_reason_label": REASON_LABELS["high_risk_unreviewed"],
            "incremental_coverage_pct": cov,
            "coverage_source": "ci",
            "high_risk_meta": hr_meta,
            "high_risk_details": details,
        }

    return {
        **base,
        "gate": "PASS",
        "block_reason": None,
        "block_reason_label": None,
        "incremental_coverage_pct": cov,
        "coverage_source": "ci",
    }


def reconciled_coverage_stats(gr: dict | None) -> tuple[float | None, int, int]:
    """与前端 KPI/批次列表一致：优先 命中行 ÷ 变更行。"""
    gr = gr or {}
    changed = int(gr.get("changed_lines") or 0)
    hit = int(gr.get("covered_changed_lines") or 0)
    probes = gr.get("coverage_probes")
    if probes and isinstance(probes, list):
        probe_hit = sum(1 for p in probes if isinstance(p, dict) and p.get("covered") is True)
        if hit <= 0 < probe_hit:
            hit = probe_hit
    if changed > 0:
        return round(hit / changed * 100, 1), changed, hit
    cov = gr.get("incremental_coverage_pct")
    return (round(float(cov), 1) if cov is not None else None), changed, hit


def threshold_for_repo(job: AnalysisJob, repo: Repository | None, default: int = 80) -> int:
    if repo and repo.full_name == job.repo_full_name:
        return repo.coverage_threshold
    return default


def job_needs_gate_refresh(job: AnalysisJob) -> bool:
    if job.gate_result is None:
        return True
    if job.status != "completed":
        return False
    gr = job.gate_result or {}
    return gr.get("gate") == "PENDING" and is_zero_impact_job(job)


def reconcile_gates_for_jobs(jobs: list[AnalysisJob], db) -> None:
    """回填缺失门禁，或将「零影响却仍 PENDING」的作业改为 PASS。"""
    from sqlalchemy import select

    from app.db.models import Repository

    dirty = False
    for job in jobs:
        if not job_needs_gate_refresh(job):
            continue
        repo = db.scalar(select(Repository).where(Repository.full_name == job.repo_full_name))
        apply_gate_result(job, repo)
        dirty = True
    if dirty:
        db.commit()


def apply_manual_override(
    job: AnalysisJob,
    *,
    reason_category: str,
    reason_detail: str,
    actor: str = "admin",
    auditor_role: str = "qa",
    repo: Repository | None = None,
) -> dict[str, Any]:
    gr = dict(job.gate_result or {})
    if str(gr.get("gate") or "").upper() != "BLOCK":
        raise ValueError("仅 BLOCK 状态的批次可人工豁免")

    if gr.get("allow_override") is False:
        raise ValueError("当前批次命中不可豁免路径规则，请联系负责人处理")

    paths = changed_paths_from_job(job)
    if repo and not override_allowed_for_job(paths, getattr(repo, "gate_path_rules", None)):
        raise ValueError("变更涉及禁止豁免路径（如支付核心模块）")

    label = OVERRIDE_REASON_LABELS.get(reason_category, reason_category)
    now = datetime.utcnow().isoformat() + "Z"
    gr.update(
        {
            "gate": "OVERRIDDEN",
            "gate_label": "PASS（人工豁免）",
            "previous_block_reason": gr.get("block_reason"),
            "previous_block_reason_label": gr.get("block_reason_label"),
            "block_reason": None,
            "block_reason_label": None,
            "manual_override": {
                "actor": actor,
                "auditor_role": auditor_role,
                "at": now,
                "reason_category": reason_category,
                "reason_category_label": label,
                "reason_detail": reason_detail.strip(),
            },
            "override_audit": {
                "auditor_id": actor,
                "auditor_role": auditor_role,
                "at": now,
                "reason_category": reason_category,
                "reason_category_label": label,
                "reason_detail": reason_detail.strip(),
                "immutable": True,
            },
        }
    )
    job.gate_result = gr
    return gr


def apply_gate_result(
    job: AnalysisJob,
    repo: Repository | None,
    *,
    incremental_coverage_pct: float | None = None,
    tests_passed: bool | None = None,
    coverage_probes: list[dict[str, Any]] | None = None,
    covered_changed_lines: int | None = None,
    api_smoke_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    threshold = threshold_for_repo(job, repo)
    prev = job.gate_result or {}
    if prev.get("gate") == "OVERRIDDEN" and prev.get("manual_override"):
        updated = dict(prev)
        if incremental_coverage_pct is not None:
            updated["incremental_coverage_pct"] = float(incremental_coverage_pct)
        if tests_passed is not None:
            updated["tests_passed"] = bool(tests_passed)
        if coverage_probes is not None:
            updated["coverage_probes"] = coverage_probes
            if covered_changed_lines is not None:
                updated["covered_changed_lines"] = int(covered_changed_lines)
        if api_smoke_results is not None:
            updated["api_smoke_results"] = api_smoke_results
        job.gate_result = updated
        return updated
    cov = incremental_coverage_pct
    if cov is None and prev.get("incremental_coverage_pct") is not None:
        cov = float(prev["incremental_coverage_pct"])
    tests = tests_passed
    if tests is None and prev.get("tests_passed") is not None:
        tests = bool(prev["tests_passed"])

    result = build_gate_result(
        job,
        threshold=threshold,
        incremental_coverage_pct=cov,
        tests_passed=tests,
        repo=repo,
    )
    probes = coverage_probes
    if probes is None and prev.get("coverage_probes"):
        probes = prev.get("coverage_probes")
    if probes is not None:
        result["coverage_probes"] = probes
        if covered_changed_lines is not None:
            result["covered_changed_lines"] = int(covered_changed_lines)
        else:
            result["covered_changed_lines"] = sum(
                1 for p in probes if isinstance(p, dict) and p.get("covered") is True
            )
    smoke = api_smoke_results
    if smoke is None and prev.get("api_smoke_results"):
        smoke = prev.get("api_smoke_results")
    if smoke is not None:
        result["api_smoke_results"] = smoke

    cl = int(result.get("changed_lines") or 0)
    hit = result.get("covered_changed_lines")
    if hit is not None and cl > 0:
        reconciled = round(float(hit) / cl * 100, 1)
        prev_cov = result.get("incremental_coverage_pct")
        result["incremental_coverage_pct"] = reconciled
        if prev_cov != reconciled or result.get("coverage_source") == "ci":
            refreshed = build_gate_result(
                job,
                threshold=threshold,
                incremental_coverage_pct=reconciled,
                tests_passed=result.get("tests_passed"),
                repo=repo,
            )
            for key in (
                "gate",
                "block_reason",
                "block_reason_label",
                "coverage_source",
                "incremental_coverage_pct",
            ):
                if key in refreshed:
                    result[key] = refreshed[key]
            result["incremental_coverage_pct"] = reconciled
            if probes is not None:
                result["coverage_probes"] = probes
            if smoke is not None:
                result["api_smoke_results"] = smoke
            if hit is not None:
                result["covered_changed_lines"] = int(hit)

    detail = build_trigger_detail(
        job,
        result,
        covered_changed_lines=result.get("covered_changed_lines"),
    )
    if detail:
        result["trigger_detail"] = detail
    else:
        result.pop("trigger_detail", None)

    ci = _contract_impact(job)
    if ci:
        result["cross_repo_impacts"] = {
            "breaking_hits": ci.get("breaking_hits") or [],
            "warnings": ci.get("warnings") or [],
            "impacts": ci.get("impacts") or [],
            "suggested_regression_cases": ci.get("suggested_regression_cases") or [],
            "perspective": ci.get("perspective"),
        }
    if result.get("block_reason") not in ("high_risk_unreviewed", "breaking_contract_change"):
        result.pop("high_risk_details", None)
    elif result.get("block_reason") == "breaking_contract_change" and not result.get("high_risk_details"):
        result["high_risk_details"] = build_breaking_contract_details(job)
    elif result.get("high_risk_meta") and not result.get("high_risk_details"):
        result["high_risk_details"] = build_high_risk_details(
            job, repo, result["high_risk_meta"]
        )

    job.gate_result = result
    return result


def gate_snapshot_for_dashboard(job: AnalysisJob) -> dict[str, Any]:
    gr = job.gate_result or {}
    cov, _, _ = reconciled_coverage_stats(gr)
    return {
        "commit": (job.head_sha or "")[:8],
        "repo": job.repo_full_name,
        "changed_files": int(gr.get("changed_files") or 0),
        "api_impact": int(gr.get("api_impact") or _api_count(job)),
        "coverage": cov,
        "gate": gr.get("gate") or "PENDING",
        "time": as_utc_iso(job.created_at),
        "job_id": job.id,
        "block_reason": gr.get("block_reason"),
        "block_reason_label": gr.get("block_reason_label"),
        "trigger_detail_summary": (
            (gr.get("trigger_detail") or {}).get("summary")
            if isinstance(gr.get("trigger_detail"), dict)
            else None
        ),
    }