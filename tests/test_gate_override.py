from types import SimpleNamespace

import pytest

from app.services.quality_gate import apply_manual_override


def _job_block():
    return SimpleNamespace(
        gate_result={
            "gate": "BLOCK",
            "block_reason": "incremental_coverage_low",
            "block_reason_label": "增量覆盖率不足",
        }
    )


def test_manual_override_from_block():
    job = _job_block()
    gr = apply_manual_override(
        job,
        reason_category="hotfix",
        reason_detail="已与测试负责人确认紧急发版",
        actor="admin",
    )
    assert gr["gate"] == "OVERRIDDEN"
    assert gr["manual_override"]["reason_category"] == "hotfix"
    assert job.gate_result["gate"] == "OVERRIDDEN"


def test_manual_override_rejects_non_block():
    job = SimpleNamespace(gate_result={"gate": "PASS"})
    with pytest.raises(ValueError):
        apply_manual_override(job, reason_category="other", reason_detail="ok")