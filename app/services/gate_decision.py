"""质量门禁裁决引擎：多规则命中时按优先级择一展示，并记录全部命中项。"""

from __future__ import annotations

from typing import Any

from app.db.models import AnalysisJob, Repository

# 与产品状态图一致：破坏性契约 > 高危 > 冒烟失败 > 覆盖率底线
GATE_RULE_PRIORITY: tuple[str, ...] = (
    "breaking_contract_change",
    "high_risk_unreviewed",
    "core_api_regression",
    "incremental_coverage_low",
)

GATE_DECISION_ENGINE = "priority_stack_v1"


def pick_primary_block_reason(rule_hits: list[str]) -> str | None:
    for code in GATE_RULE_PRIORITY:
        if code in rule_hits:
            return code
    return rule_hits[0] if rule_hits else None


def evaluate_coverage_phase_rules(
    base: dict[str, Any],
    job: AnalysisJob,
    repo: Repository | None,
    *,
    cov: float,
    eff_threshold: int,
    tests_passed: bool | None,
    api_count: int,
    high_risk: bool,
    hr_meta: dict[str, Any] | None,
    high_risk_details: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    在已有 incremental_coverage_pct 时，按优先级裁决 BLOCK / PASS。
    破坏性契约在 build_gate_result 更早阶段处理。
    """
    from app.services.quality_gate import REASON_LABELS

    rule_hits: list[str] = []
    if high_risk:
        rule_hits.append("high_risk_unreviewed")
    if tests_passed is False and api_count > 0:
        rule_hits.append("core_api_regression")
    if cov < eff_threshold:
        rule_hits.append("incremental_coverage_low")

    base = {
        **base,
        "gate_decision_engine": GATE_DECISION_ENGINE,
        "gate_rule_hits": rule_hits,
        "incremental_coverage_pct": cov,
        "coverage_source": "ci",
    }

    primary = pick_primary_block_reason(rule_hits)
    if not primary:
        return {
            **base,
            "gate": "PASS",
            "block_reason": None,
            "block_reason_label": None,
            "release_status": "PASS",
        }

    out: dict[str, Any] = {
        **base,
        "gate": "BLOCK",
        "block_reason": primary,
        "block_reason_label": REASON_LABELS.get(primary, primary),
        "release_status": "BLOCK",
    }
    if primary == "high_risk_unreviewed" and hr_meta is not None:
        out["high_risk_meta"] = hr_meta
        if high_risk_details is not None:
            out["high_risk_details"] = high_risk_details
    return out