from app.services.webhook_scan_filter import (
    is_repo_root_global_file,
    path_filter_skip_reason,
    path_under_scan_root,
    repo_hit_by_scan_root,
)


def test_path_under_scan_root() -> None:
    assert path_under_scan_root("frontend/src/App.vue", "frontend")
    assert not path_under_scan_root("frontend/src/App.vue", "backend")
    assert path_under_scan_root("app/main.py", ".")


def test_repo_hit_by_scan_root() -> None:
    assert repo_hit_by_scan_root(["backend/api.py"], "backend")
    assert not repo_hit_by_scan_root(["frontend/a.ts"], "backend")
    assert not repo_hit_by_scan_root([], "backend")
    assert not repo_hit_by_scan_root([], ".")
    assert repo_hit_by_scan_root(["any/file"], ".")


def test_removed_under_subdir_triggers() -> None:
    assert repo_hit_by_scan_root(["backend/app/old_api.py"], "backend")


def test_global_root_does_not_hit_subdir() -> None:
    assert is_repo_root_global_file("docker-compose.yml")
    assert not repo_hit_by_scan_root(["docker-compose.yml", ".env.example"], "backend")
    assert path_filter_skip_reason(["docker-compose.yml"], "frontend") == "skipped_global_root_only"