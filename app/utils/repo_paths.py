"""仓库内相对路径（兼容层，实现见 fullstack_normalize）。"""

from __future__ import annotations

from app.parsers.fullstack_normalize import clean_repo_rel_path


def clean_repo_relative_path(path: str | None, repo_root: str | None = None) -> str:
    return clean_repo_rel_path(path or "", repo_root)


def split_repo_path(path: str | None, repo_root: str | None = None) -> dict[str, str]:
    rel = clean_repo_rel_path(path or "", repo_root)
    if not rel:
        return {"full": "", "dir": "", "name": ""}
    parts = rel.split("/")
    name = parts[-1] if parts else rel
    dir_part = "/".join(parts[:-1]) if len(parts) > 1 else ""
    return {"full": rel, "dir": dir_part, "name": name}