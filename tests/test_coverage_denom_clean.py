from app.services.coverage_denom_clean import (
    clean_changed_lines,
    count_diff_lines,
    level1_path_reason,
)


def test_level1_non_code_and_tests():
    assert level1_path_reason("README.md") == "non_code_file"
    assert level1_path_reason("tests/foo.py") == "test_or_script_dir"
    assert level1_path_reason("backend/app/main.py", scan_root="backend") is None
    assert level1_path_reason("frontend/app.py", scan_root="backend") == "outside_scan_root"


def test_clean_filters_non_code():
    ranges = [
        {"path": "README.md", "start": 1, "end": 3},
        {"path": "backend/app/x.py", "start": 10, "end": 11},
    ]
    res = clean_changed_lines(ranges, repo_dir=None, scan_root=".")
    assert count_diff_lines(ranges) == 5
    assert res.diff_lines_total == 5
    assert res.lines_filtered == 3
    # 无 repo_dir 时不做 L2 按行清洗，.py 变更行仍计入
    assert len(res.effective) == 2