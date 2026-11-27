"""超大提交熔断：跳过逐行 AST，触发人工评审。"""

from __future__ import annotations

from pathlib import Path

ULTRA_FILE_MAX_BYTES = 500 * 1024
ULTRA_COMMIT_MAX_ADDED_LINES = 3000


def count_added_lines_per_file(line_ranges: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for block in line_ranges:
        if not isinstance(block, dict):
            continue
        path = str(block.get("path") or "").replace("\\", "/").lstrip("./")
        if not path:
            continue
        start = int(block.get("start") or 0)
        end = int(block.get("end") or start)
        if start <= 0:
            continue
        counts[path] = counts.get(path, 0) + max(0, end - start + 1)
    return counts


def ultra_large_skip_reason(path: str, repo_dir: Path | None, added_lines: int) -> str | None:
    if added_lines > ULTRA_COMMIT_MAX_ADDED_LINES:
        return "ultra_large_commit_lines"
    if repo_dir is not None:
        try:
            fp = (repo_dir / path).resolve()
            if fp.is_file() and fp.stat().st_size > ULTRA_FILE_MAX_BYTES:
                return "ultra_large_file_bytes"
        except OSError:
            pass
    return None