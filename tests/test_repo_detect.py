from pathlib import Path

from app.services.repo_detect_fingerprint import detect_from_directory
from app.services.repo_directory_analyzer import analyze_directory_tree, run_directory_analysis
from app.services.repo_scan_directories import build_directories


def test_detect_go_mod(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/foo\n\ngo 1.22\n", encoding="utf-8")
    r = detect_from_directory(tmp_path)
    assert r.repo_type == "backend_go"
    assert r.scan_root == "."


def test_detect_java_maven(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project></project>", encoding="utf-8")
    src = tmp_path / "src" / "main" / "java"
    src.mkdir(parents=True)
    r = detect_from_directory(tmp_path)
    assert r.repo_type == "backend_java"
    assert r.scan_root == "src/main/java"


def test_detect_python_requirements(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    r = detect_from_directory(tmp_path)
    assert r.repo_type == "backend_python"


def test_detect_frontend_package(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"react":"^18.0.0","vite":"^5.0.0"}}',
        encoding="utf-8",
    )
    r = detect_from_directory(tmp_path)
    assert r.repo_type == "frontend"


def test_analyze_directory_tree_monorepo() -> None:
    all_files = [
        "README.md",
        "docker-compose.yml",
        "backend/requirements.txt",
        "backend/app/main.py",
        "frontend/package.json",
        "frontend/src/index.ts",
    ]
    contents = {
        "frontend/package.json": '{"dependencies":{"vue":"3"}}',
    }
    r = analyze_directory_tree(all_files, contents)
    assert r["is_monorepo"] is True
    assert r["recommended_root"] == "backend"
    assert r["detected_type"] == "python"
    paths = {d["path"] for d in r["directories"]}
    assert "backend" in paths
    assert "frontend" in paths


def test_scan_directory_options_monorepo(tmp_path: Path) -> None:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "frontend" / "package.json").write_text('{"dependencies":{"vue":"3"}}', encoding="utf-8")
    (tmp_path / "backend" / "requirements.txt").write_text("django\n", encoding="utf-8")
    fp = detect_from_directory(tmp_path)
    opts = build_directories(fp, repo_dir=tmp_path)
    analyzed = run_directory_analysis(repo_dir=tmp_path)
    assert analyzed["recommended_root"] == "backend"
    paths = {o["path"] for o in opts}
    assert "node_modules" not in paths
    assert "backend" in paths
    assert "frontend" in paths
    rec = {o["path"] for o in opts if o.get("is_recommended")}
    assert "backend" in rec
    backend = next(o for o in opts if o["path"] == "backend")
    assert backend["matched_type"] == "python"
    assert backend["label"] == "backend"
    assert backend.get("file_summary")

def test_monorepo_hint(tmp_path: Path) -> None:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text('{"dependencies":{"vue":"3"}}', encoding="utf-8")
    (tmp_path / "backend" / "requirements.txt").write_text("django\n", encoding="utf-8")
    r = detect_from_directory(tmp_path)
    assert r.is_monorepo
    assert r.repo_type == "backend_python"
    assert r.scan_root == "backend"