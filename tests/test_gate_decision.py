from types import SimpleNamespace

from app.services.gate_decision import pick_primary_block_reason
from app.services.quality_gate import build_gate_result


def test_pick_primary_block_reason_order():
    hits = ["incremental_coverage_low", "high_risk_unreviewed", "core_api_regression"]
    assert pick_primary_block_reason(hits) == "high_risk_unreviewed"


def test_high_risk_wins_over_low_coverage():
    job = SimpleNamespace(
        status="completed",
        affected_apis={"count": 6, "apis": [{}] * 6},
        changed_symbols={
            "line_ranges": [{"path": "app/payment/charge.py", "start": 1, "end": 5}],
            "symbols": ["x"],
            "suspects": [{"file": "app/payment/charge.py", "qualified_name": "charge"}],
        },
    )
    repo = SimpleNamespace(
        full_name="acme/x",
        coverage_threshold=80,
        high_risk_paths=["app/payment/*"],
        gate_path_rules=None,
    )
    gr = build_gate_result(
        job,
        threshold=80,
        incremental_coverage_pct=50.0,
        tests_passed=True,
        repo=repo,
    )
    assert gr["gate"] == "BLOCK"
    assert gr["block_reason"] == "high_risk_unreviewed"
    assert "incremental_coverage_low" in gr.get("gate_rule_hits", [])