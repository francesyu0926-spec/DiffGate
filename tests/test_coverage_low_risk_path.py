from types import SimpleNamespace

from app.services.coverage_denom_clean import clean_changed_lines


def test_low_risk_whitelist_excludes_from_denom():
    repo = SimpleNamespace(
        low_risk_paths=["app/grpc_pb2/**"],
    )
    ranges = [{"path": "app/grpc_pb2/foo_pb2.py", "start": 10, "end": 12}]
    res = clean_changed_lines(ranges, repo_dir=None, repo=repo)
    assert res.executable_changed_lines == 0
    assert res.ignored[0][2] == "low_risk_whitelist"