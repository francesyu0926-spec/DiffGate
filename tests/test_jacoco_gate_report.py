from pathlib import Path

from app.services.jacoco_gate_report import parse_jacoco_line_hits, probes_from_jacoco

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<report name="Demo">
  <package name="com/example">
    <sourcefile name="com/example/OrderService.java">
      <line nr="10" mi="0" ci="2" mb="0" cb="0"/>
      <line nr="42" mi="1" ci="0" mb="0" cb="0"/>
    </sourcefile>
  </package>
</report>
"""


def test_parse_jacoco_line_hits(tmp_path: Path):
    xml = tmp_path / "jacoco.xml"
    xml.write_text(SAMPLE, encoding="utf-8")
    hits = parse_jacoco_line_hits(xml)
    assert hits["com/example/OrderService.java"] == {10}


def test_probes_from_jacoco(tmp_path: Path):
    xml = tmp_path / "jacoco.xml"
    xml.write_text(SAMPLE, encoding="utf-8")
    effective = [
        ("com/example/OrderService.java", 10),
        ("com/example/OrderService.java", 42),
    ]
    probes, covered, total = probes_from_jacoco(xml, effective)
    assert total == 2
    assert covered == 1
    assert probes[0]["covered"] is True
    assert probes[1]["covered"] is False