from pathlib import Path

from app.parsers.frontend_contract import (
    apply_api_base_prefix,
    normalize_frontend_api_path,
)
from app.services.contract_impact import parse_git_route_removals


def test_api_base_prefix_join():
    assert apply_api_base_prefix("/jobs", "/api/v1") == "/api/v1/jobs"
    assert normalize_frontend_api_path("/jobs/${id}", api_base_prefix="/api/v1") == "/api/v1/jobs/*"


def test_git_route_removal(tmp_path: Path):
    (tmp_path / "a.py").write_text(
        '@router.get("/users")\ndef u():\n    pass\n',
        encoding="utf-8",
    )
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    (tmp_path / "a.py").write_text("def u():\n    pass\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "remove"], cwd=tmp_path, check=True, capture_output=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    removed = parse_git_route_removals(tmp_path, base, head)
    assert any(r.get("path") == "/users" for r in removed)