from app.services.coverage_probe_merge import append_probe_report_history, merge_coverage_probes_union


def test_merge_union_keeps_prior_hits():
    prev = [{"file": "a.py", "line": 1, "covered": True}]
    new = [{"file": "a.py", "line": 2, "covered": True}, {"file": "a.py", "line": 1, "covered": False}]
    merged = merge_coverage_probes_union(prev, new)
    by_line = {row["line"]: row["covered"] for row in merged}
    assert by_line[1] is True
    assert by_line[2] is True


def test_probe_history_cap():
    hist = append_probe_report_history([], {"at": "1"}, limit=5)
    for i in range(10):
        hist = append_probe_report_history(hist, {"at": str(i)}, limit=5)
    assert len(hist) == 5
    assert hist[-1]["at"] == "9"