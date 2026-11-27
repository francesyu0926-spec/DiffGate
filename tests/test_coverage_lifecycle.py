from pathlib import Path

from app.services.coverage_lifecycle import coverage_reset


def test_coverage_reset_removes_files(tmp_path: Path):
    (tmp_path / ".coverage").write_text("x")
    (tmp_path / ".coverage.12345").write_text("y")
    n = coverage_reset(tmp_path)
    assert n == 2
    assert not list(tmp_path.glob(".coverage*"))