"""对比 base/head 函数语义哈希，过滤纯格式化变更。"""

from __future__ import annotations

from pathlib import Path

from git import Repo

from app.engine.impact_types import SuspectFunction
from app.parsers.ast_hash import function_body_hash


def _file_at_sha(repo: Repo, sha: str, path: str) -> str | None:
    try:
        blob = repo.commit(sha).tree / path
        return blob.data_stream.read().decode("utf-8", errors="replace")
    except (KeyError, OSError, ValueError):
        return None


def drop_cosmetic_suspects(
    repo_path: Path,
    base_sha: str,
    head_sha: str,
    suspects: list[SuspectFunction],
) -> list[SuspectFunction]:
    if not suspects:
        return suspects
    repo = Repo(str(repo_path))
    kept: list[SuspectFunction] = []
    for s in suspects:
        base_src = _file_at_sha(repo, base_sha, s.file_path)
        head_src = _file_at_sha(repo, head_sha, s.file_path)
        if not base_src or not head_src:
            kept.append(s)
            continue
        h0 = function_body_hash(base_src, s.qualified_name)
        h1 = function_body_hash(head_src, s.qualified_name)
        if h0 and h1 and h0 == h1:
            continue
        kept.append(s)
    return kept