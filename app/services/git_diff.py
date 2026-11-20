from dataclasses import dataclass
from pathlib import Path

from git import Repo


@dataclass
class LineRange:
    path: str
    start: int
    end: int


def get_changed_line_ranges(repo_path: str | Path, base_sha: str, head_sha: str) -> list[LineRange]:
    """Extract changed file paths and line ranges from git diff base..head."""
    repo = Repo(str(repo_path))
    diff_index = repo.commit(base_sha).diff(repo.commit(head_sha), create_patch=True)

    ranges: list[LineRange] = []
    for diff_item in diff_index:
        if diff_item.deleted_file:
            path = diff_item.a_path or ""
        else:
            path = diff_item.b_path or diff_item.a_path or ""
        if not path or not path.endswith(".py"):
            continue

        patch = diff_item.diff.decode("utf-8", errors="replace") if diff_item.diff else ""
        current_start: int | None = None
        current_end: int | None = None
        new_line = 0

        for line in patch.splitlines():
            if line.startswith("@@"):
                parts = line.split("+")
                if len(parts) >= 2:
                    segment = parts[1].split("@@")[0].strip()
                    new_line = int(segment.split(",")[0]) - 1
                if current_start is not None and current_end is not None:
                    ranges.append(LineRange(path=path, start=current_start, end=current_end))
                current_start = None
                current_end = None
                continue
            if line.startswith("+") and not line.startswith("+++"):
                new_line += 1
                if current_start is None:
                    current_start = new_line
                current_end = new_line
            elif line.startswith(" ") or line.startswith("+"):
                if line.startswith(" "):
                    new_line += 1
                if current_start is not None and current_end is not None:
                    ranges.append(LineRange(path=path, start=current_start, end=current_end))
                    current_start = None
                    current_end = None
            elif line.startswith("-") and not line.startswith("---"):
                pass

        if current_start is not None and current_end is not None:
            ranges.append(LineRange(path=path, start=current_start, end=current_end))

    return ranges