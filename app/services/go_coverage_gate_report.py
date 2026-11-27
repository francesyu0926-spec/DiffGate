"""Go coverage.out / covdata textfmt → gate-report 探针。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def parse_go_coverage_profile(path: Path) -> dict[str, dict[int, int]]:
    """
    解析 go tool cover / textfmt 输出：
    path:startLine.col,endLine.col statements count hits
  返回 path -> {line: hits}
    """
    hits: dict[str, dict[int, int]] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("mode:"):
            continue
        if ":" not in line:
            continue
        file_part, rest = line.split(":", 1)
        file_path = file_part.strip().replace("\\", "/")
        bucket = hits.setdefault(file_path, {})
        chunks = rest.split()
        if len(chunks) < 3:
            continue
        span = chunks[0]
        try:
            hit_count = int(chunks[-1])
        except ValueError:
            continue
        if hit_count <= 0:
            continue
        if "." in span:
            start_s = span.split(",")[0]
            line_no = int(start_s.split(".")[0])
        else:
            line_no = int(span.split(",")[0])
        bucket[line_no] = hit_count
    return hits


def probes_from_go_coverage(
    profile_path: Path,
    effective_lines: list[tuple[str, int]],
) -> tuple[list[dict[str, Any]], int, int]:
    hit_map = parse_go_coverage_profile(profile_path)
    probes: list[dict[str, Any]] = []
    covered = 0
    for path, line in effective_lines:
        norm = path.replace("\\", "/")
        file_hits = hit_map.get(norm) or hit_map.get(norm.lstrip("./"))
        hit = bool(file_hits and line in file_hits)
        if hit:
            covered += 1
        probes.append({"file": norm, "line": line, "covered": hit, "prefix": "+"})
    return probes, covered, len(effective_lines)