"""同一 AnalysisJob 多次 gate-report 探针按行号并集合并。"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _probe_key(row: dict) -> tuple[str, int]:
    return (str(row.get("file") or ""), int(row.get("line") or 0))


def merge_coverage_probes_union(
    previous: list[dict] | None,
    incoming: list[dict] | None,
) -> list[dict]:
    if not incoming:
        return list(previous or [])
    if not previous:
        return list(incoming)
    merged: dict[tuple[str, int], dict] = {}
    for row in previous:
        if isinstance(row, dict):
            merged[_probe_key(row)] = dict(row)
    for row in incoming:
        if not isinstance(row, dict):
            continue
        key = _probe_key(row)
        old = merged.get(key)
        if old is None:
            merged[key] = dict(row)
            continue
        combined = dict(old)
        if row.get("covered") is True or old.get("covered") is True:
            combined["covered"] = True
        elif row.get("covered") is not None:
            combined["covered"] = row.get("covered")
        for field in ("ignored", "filter_reason", "prefix"):
            if field in row and row[field] is not None:
                combined[field] = row[field]
        merged[key] = combined
    return sorted(
        merged.values(),
        key=lambda x: (str(x.get("file") or ""), int(x.get("line") or 0)),
    )


def append_probe_report_history(
    history: list[dict] | None,
    snapshot: dict[str, Any],
    *,
    limit: int = 5,
) -> list[dict]:
    hist = [h for h in (history or []) if isinstance(h, dict)]
    hist.append(snapshot)
    return hist[-limit:]


def snapshot_from_gate_report(
    *,
    running_commit_sha: str | None,
    covered_changed_lines: int | None,
    probe_count: int,
    incremental_coverage_pct: float | None,
) -> dict[str, Any]:
    return {
        "at": datetime.utcnow().isoformat(),
        "running_commit_sha": running_commit_sha,
        "covered_changed_lines": covered_changed_lines,
        "probe_count": probe_count,
        "incremental_coverage_pct": incremental_coverage_pct,
    }