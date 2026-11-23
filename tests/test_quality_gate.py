from types import SimpleNamespace

from app.services.quality_gate import build_gate_result


def _job(**kw):
    defaults = {
        "status": "completed",
        "affected_apis": {"count": 2},
        "changed_symbols": {"line_ranges": [{"path": "a.py", "start": 1, "end": 10}], "symbols": ["a.f"]},
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _repo(threshold=80):
    return SimpleNamespace(full_name="acme/x", coverage_threshold=threshold)


def test_block_when_coverage_below_threshold():
    job = _job()
    gr = build_gate_result(job, threshold=80, incremental_coverage_pct=75.0, tests_passed=True)
    assert gr["gate"] == "BLOCK"
    assert gr["block_reason"] == "incremental_coverage_low"


def test_pass_when_coverage_ok():
    job = _job()
    gr = build_gate_result(job, threshold=80, incremental_coverage_pct=88.0, tests_passed=True)
    assert gr["gate"] == "PASS"


def test_pending_without_coverage():
    job = _job()
    gr = build_gate_result(job, threshold=80)
    assert gr["gate"] == "PENDING"


def test_auto_pass_zero_impact_without_coverage():
    job = _job(
        affected_apis={"count": 0, "apis": [], "call_paths": []},
        changed_symbols={"symbols": [], "suspects": [], "line_ranges": []},
    )
    gr = build_gate_result(job, threshold=80)
    assert gr["gate"] == "PASS"
    assert gr["coverage_source"] == "auto_zero_impact"