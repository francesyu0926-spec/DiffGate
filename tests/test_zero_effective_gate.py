from types import SimpleNamespace

from app.services.quality_gate import _zero_effective_lines_coverage_pass, build_gate_result


def _job(changed_symbols: dict):
    return SimpleNamespace(
        changed_symbols=changed_symbols,
        affected_apis={"apis": [], "count": 1},
        gate_result=None,
        repo_full_name="acme/demo",
        id="job-test",
        status="completed",
    )


def test_zero_effective_lines_yields_pass_not_zero_pct_block():
    job = _job({"line_ranges": [{"path": "README.md", "start": 1, "end": 5}]})
    base = build_gate_result(
        job,
        threshold=80,
        incremental_coverage_pct=0.0,
        tests_passed=True,
        repo=None,
    )
    assert base.get("coverage_not_required") is True
    out = _zero_effective_lines_coverage_pass(
        {
            **base,
            "diff_lines_total": 5,
            "executable_changed_lines": 0,
            "changed_lines": 0,
            "incremental_coverage_pct": 0.0,
        },
        job,
        None,
        80,
    )
    assert out.get("coverage_not_required") is True
    assert out.get("incremental_coverage_pct") is None
    assert out.get("gate") == "PASS"