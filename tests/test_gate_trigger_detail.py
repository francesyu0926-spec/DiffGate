from types import SimpleNamespace

from app.services.quality_gate import (
    HIGH_RISK_API_THRESHOLD,
    HIGH_RISK_SYMBOL_THRESHOLD,
    apply_gate_result,
    build_trigger_detail,
)


def _job(**kw):
    apis = [
        {"method": "GET", "path": f"/api/{i}", "file": f"app/r{i}.py"} for i in range(11)
    ]
    suspects = [{"qualified_name": f"mod.fn_{i}", "file": f"app/s{i}.py"} for i in range(10)]
    defaults = {
        "status": "completed",
        "affected_apis": {"count": len(apis), "apis": apis},
        "changed_symbols": {"symbols": [s["qualified_name"] for s in suspects], "suspects": suspects},
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_trigger_detail_high_risk():
    job = _job()
    gr = {
        "gate": "BLOCK",
        "block_reason": "high_risk_unreviewed",
        "block_reason_label": "高危模块未评审",
        "api_impact": 11,
        "symbol_count": 10,
        "coverage_threshold": 80,
        "incremental_coverage_pct": 90.0,
    }
    td = build_trigger_detail(job, gr)
    assert td is not None
    assert "11" in td["summary"]
    assert str(HIGH_RISK_API_THRESHOLD) in td["summary"]
    assert len(td["high_risk_items"]["apis"]) == 8
    assert len(td["high_risk_items"]["symbols"]) == 10


def test_apply_gate_result_attaches_trigger_detail():
    job = _job()
    job.repo_full_name = "acme/x"
    job.gate_result = None
    repo = SimpleNamespace(full_name="acme/x", coverage_threshold=80)
    gr = apply_gate_result(
        job,
        repo,
        incremental_coverage_pct=88.0,
        tests_passed=True,
        covered_changed_lines=100,
    )
    assert gr["gate"] == "BLOCK"
    assert gr.get("trigger_detail", {}).get("kind") == "high_risk_unreviewed"