from app.services.coverage_path_norm import match_repo_relative_path, normalize_probe_dicts


def test_match_absolute_container_path():
    candidates = {"backend/app/service.py"}
    assert (
        match_repo_relative_path(
            "/app/src/backend/app/service.py",
            candidates,
            scan_root="backend",
        )
        == "backend/app/service.py"
    )


def test_normalize_probe_dicts():
    probes = [{"file": "/workspace/backend/foo.py", "line": 10, "covered": True}]
    out = normalize_probe_dicts(
        probes,
        scan_root="backend",
        candidate_paths={"backend/foo.py"},
    )
    assert out[0]["file"] == "backend/foo.py"