from types import SimpleNamespace

from app.services.high_risk_paths import evaluate_high_risk, path_matches_pattern
from app.services.quality_gate import build_gate_result


def test_path_matches_glob():
    assert path_matches_pattern("app/payment/charge.py", "app/payment/*")
    assert path_matches_pattern("lib/auth.py", "**/auth.py")


def test_core_path_triggers_high_risk():
    repo = SimpleNamespace(high_risk_paths=["app/payment/*"])
    job = SimpleNamespace(
        changed_symbols={
            "line_ranges": [{"path": "app/payment/charge.py", "start": 1, "end": 2}],
            "symbols": ["x"],
        }
    )
    hit, meta = evaluate_high_risk(job, repo, api_count=1, symbol_count=1)
    assert hit is True
    assert meta["mode"] == "core_path"


def test_platform_threshold_when_configured_paths_but_no_hit():
    repo = SimpleNamespace(high_risk_paths=["app/payment/*"])
    job = SimpleNamespace(changed_symbols={"line_ranges": [{"path": "lib/util.py", "start": 1, "end": 2}]})
    hit, meta = evaluate_high_risk(job, repo, api_count=4, symbol_count=7)
    assert hit is False
    assert meta["api_threshold"] == 5
    hit2, meta2 = evaluate_high_risk(job, repo, api_count=5, symbol_count=8)
    assert hit2 is True
    assert meta2["threshold_triggered"] is True


def test_build_high_risk_details_path_and_threshold():
    from app.services.high_risk_paths import build_high_risk_details

    repo = SimpleNamespace(high_risk_paths=["app/payment/*"])
    job = SimpleNamespace(
        changed_symbols={
            "line_ranges": [{"path": "app/payment/x.py", "start": 1, "end": 2}],
            "suspects": [{"file": "app/payment/x.py", "qualified_name": "refund"}],
        }
    )
    _, meta = evaluate_high_risk(job, repo, api_count=11, symbol_count=10)
    details = build_high_risk_details(job, repo, meta)
    assert "path_rule" in details["triggered_by"]
    assert "threshold" in details["triggered_by"]
    assert details["matched_modules"][0]["file"] == "app/payment/x.py"


def test_payment_path_effective_threshold():
    job = SimpleNamespace(
        status="completed",
        affected_apis={"count": 1, "apis": [{}]},
        changed_symbols={
            "line_ranges": [{"path": "app/payment/charge.py", "start": 1, "end": 5}],
            "symbols": ["x"],
        },
    )
    repo = SimpleNamespace(
        full_name="acme/x",
        coverage_threshold=80,
        gate_path_rules=[{"path_prefix": "app/payment/", "threshold": 95, "allow_override": False}],
        high_risk_paths=None,
    )
    gr = build_gate_result(
        job,
        threshold=80,
        incremental_coverage_pct=92.0,
        tests_passed=True,
        repo=repo,
    )
    assert gr["gate"] == "BLOCK"
    assert gr["path_gate_rule"] == "app/payment/"
    assert gr["allow_override"] is False