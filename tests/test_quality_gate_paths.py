from types import SimpleNamespace

from app.services.quality_gate import build_gate_result


def test_block_payment_path_at_95():
    job = SimpleNamespace(
        status="completed",
        affected_apis={"count": 1, "apis": [{}]},
        changed_symbols={
            "line_ranges": [{"path": "app/payment/charge.py", "start": 1, "end": 5}],
            "symbols": ["x"],
        },
    )
    gr = build_gate_result(
        job,
        threshold=95,
        incremental_coverage_pct=92.0,
        tests_passed=True,
        path_gate_rule="app/payment/",
        allow_override=False,
    )
    assert gr["gate"] == "BLOCK"