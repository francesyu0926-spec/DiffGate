"""从 Webhook payload 提取 commit 作者信息（供 RBAC 防自审）。"""

from __future__ import annotations

from typing import Any


def author_from_push_commit(commit: dict[str, Any] | None) -> dict[str, str]:
    if not commit or not isinstance(commit, dict):
        return {}
    author = commit.get("author") or {}
    username = str(author.get("username") or author.get("name") or "").strip()
    email = str(author.get("email") or "").strip()
    out: dict[str, str] = {}
    if username:
        out["committer"] = username
        out["commit_author_username"] = username
    if email:
        out["commit_author_email"] = email
    return out