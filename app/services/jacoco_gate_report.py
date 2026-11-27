"""JaCoCo XML → DiffGate gate-report 探针列表。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def parse_jacoco_line_hits(xml_path: Path) -> dict[str, set[int]]:
    """解析 jacoco.xml：返回 repo 相对路径 → 命中行号集合（ci>0 或 mb>0）。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    hits: dict[str, set[int]] = {}
    for sf in root.iter("sourcefile"):
        name = (sf.attrib.get("name") or "").replace("\\", "/")
        if not name:
            continue
        bucket = hits.setdefault(name, set())
        for line in sf.findall("line"):
            nr = int(line.attrib.get("nr") or 0)
            ci = int(line.attrib.get("ci") or 0)
            mb = int(line.attrib.get("mb") or 0)
            if nr > 0 and (ci > 0 or mb > 0):
                bucket.add(nr)
    return hits


def probes_from_jacoco(
    xml_path: Path,
    effective_lines: list[tuple[str, int]],
) -> tuple[list[dict[str, Any]], int, int]:
    """
    与 git diff 有效行求交，输出 gate-report coverage_probes。
    返回 (probes, covered_count, total_count)。
    """
    hit_map = parse_jacoco_line_hits(xml_path)
    probes: list[dict[str, Any]] = []
    covered = 0
    for path, line in effective_lines:
        norm = path.replace("\\", "/")
        hit = norm in hit_map and line in hit_map[norm]
        if hit:
            covered += 1
        probes.append(
            {
                "file": norm,
                "line": line,
                "covered": hit,
                "prefix": "+",
            }
        )
    return probes, covered, len(effective_lines)