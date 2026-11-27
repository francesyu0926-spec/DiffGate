from types import SimpleNamespace

from app.services.high_risk_paths import evaluate_high_risk, risk_weighted_counts


def test_low_risk_paths_excluded_from_threshold():
    repo = SimpleNamespace(
        high_risk_paths=[],
        low_risk_paths=["tests/**"],
        high_risk_api_threshold=None,
        high_risk_symbol_threshold=None,
    )
    job = SimpleNamespace(
        affected_apis={
            "count": 6,
            "apis": [{"file": "tests/test_foo.py", "path": "/x", "method": "GET"}] * 6,
        },
        changed_symbols={
            "symbols": ["t.a", "t.b"],
            "suspects": [
                {"qualified_name": "t.a", "file": "tests/test_foo.py"},
                {"qualified_name": "t.b", "file": "tests/test_foo.py"},
            ],
            "line_ranges": [{"path": "tests/test_foo.py", "start": 1, "end": 5}],
        },
    )
    w_api, w_sym, _, _ = risk_weighted_counts(job, repo)
    assert w_api == 0
    assert w_sym == 0
    hit, _ = evaluate_high_risk(job, repo, api_count=w_api, symbol_count=w_sym)
    assert hit is False