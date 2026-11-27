from types import SimpleNamespace

from app.services.coverage_probe import (
    count_line_range_lines,
    expand_changed_lines,
    guess_python_workdir,
    run_coverage_probe,
    _probe_rows,
)


def test_expand_changed_lines_caps():
    rows = expand_changed_lines([{"path": "a.py", "start": 1, "end": 5}])
    assert len(rows) == 5
    assert rows[0] == ("a.py", 1)


def test_guess_python_workdir():
    root = guess_python_workdir(
        __import__("pathlib").Path("/repo"),
        [{"path": "backend/app/foo.py", "start": 1, "end": 2}],
    )
    assert root.as_posix().endswith("backend")


def test_probe_rows_marks_hits():
    changed = [("a.py", 1), ("a.py", 2)]
    executed = {("a.py", 2)}
    rows = _probe_rows(changed, executed)
    assert rows[0]["covered"] is False
    assert rows[1]["covered"] is True


def test_count_line_range_lines():
    assert count_line_range_lines([{"path": "a.py", "start": 1, "end": 3}]) == 3


def test_run_coverage_probe_empty_ranges():
    out = run_coverage_probe(
        repo_dir=__import__("pathlib").Path("."),
        scan_root=".",
        interfaces=[],
        line_ranges=[],
    )
    assert out.incremental_coverage_pct == 100.0
    assert out.tests_passed is True


def test_suspect_fallback_when_no_deps(tmp_path):
    job = SimpleNamespace(
        changed_symbols={
            "suspects": [
                {"file": "x.py", "start_line": 2, "end_line": 4},
            ]
        }
    )
    out = run_coverage_probe(
        repo_dir=tmp_path,
        scan_root=".",
        interfaces=[{"method": "GET", "path": "/nope"}],
        line_ranges=[{"path": "x.py", "start": 2, "end": 3}],
        job=job,
    )
    assert out.changed_lines == 2
    assert out.incremental_coverage_pct >= 50.0