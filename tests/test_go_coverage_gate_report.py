from pathlib import Path

from app.services.go_coverage_gate_report import parse_go_coverage_profile, probes_from_go_coverage

SAMPLE = """
mode: set
handlers/orders.go:10.2,12.3 1 1
handlers/orders.go:42.1,42.5 1 0
"""


def test_parse_go_coverage(tmp_path: Path):
    p = tmp_path / "coverage.out"
    p.write_text(SAMPLE.strip(), encoding="utf-8")
    hits = parse_go_coverage_profile(p)
    assert 10 in hits["handlers/orders.go"]
    assert 42 not in hits.get("handlers/orders.go", {})


def test_probes_from_go_coverage(tmp_path: Path):
    p = tmp_path / "coverage.out"
    p.write_text(SAMPLE.strip(), encoding="utf-8")
    effective = [("handlers/orders.go", 10), ("handlers/orders.go", 42)]
    probes, covered, total = probes_from_go_coverage(p, effective)
    assert total == 2
    assert covered == 1
    assert probes[0]["covered"] is True