from types import SimpleNamespace

from app.services.global_infra_change import detect_global_infrastructure_change


def test_detect_global_infra_when_ratio_high():
    job = SimpleNamespace(
        changed_symbols={"line_ranges": [{"path": "backend/app/settings.py", "start": 1, "end": 2}]},
        affected_apis={"apis": [{"path": "/a"}] * 60, "call_paths": []},
    )
    repo = SimpleNamespace(ast_api_count=80)
    meta = detect_global_infrastructure_change(job, repo)
    assert meta is not None
    assert meta["label"] == "全局基础设施变更"
    assert meta["affected_api_ratio"] >= 0.5