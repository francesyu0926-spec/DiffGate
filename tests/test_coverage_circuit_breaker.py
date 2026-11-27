from pathlib import Path

from app.services.coverage_circuit_breaker import (
    ULTRA_COMMIT_MAX_ADDED_LINES,
    ultra_large_skip_reason,
)
from app.services.coverage_denom_clean import clean_changed_lines


def test_ultra_large_by_line_count():
    reason = ultra_large_skip_reason(
        "pkg/lock.json",
        None,
        ULTRA_COMMIT_MAX_ADDED_LINES + 1,
    )
    assert reason == "ultra_large_commit_lines"


def test_clean_skips_ast_for_ultra_file(tmp_path):
    small = tmp_path / "huge.py"
    small.write_text("x = 1\n")
    ranges = [{"path": "huge.py", "start": 1, "end": ULTRA_COMMIT_MAX_ADDED_LINES + 5}]
    out = clean_changed_lines(ranges, repo_dir=tmp_path, scan_root=".")
    assert "huge.py" in out.ultra_large_files
    assert out.executable_changed_lines == 0