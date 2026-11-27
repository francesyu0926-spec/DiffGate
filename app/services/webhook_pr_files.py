"""MR/PR 变更文件列表（GitHub / GitLab API）。"""

from __future__ import annotations

import logging
import urllib.parse

import httpx

from app.services.repo_detect_parse import parse_clone_url_meta

logger = logging.getLogger(__name__)


def _pick_token(repos: list) -> str | None:
    for r in repos:
        tok = (getattr(r, "access_token", None) or "").strip()
        if tok:
            return tok
    return None


def github_pr_changed_files(
    *,
    clone_url: str,
    pr_number: int,
    token: str | None,
) -> list[str]:
    meta = parse_clone_url_meta(clone_url, "github")
    if not meta:
        return []
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    paths: list[str] = []
    page = 1
    with httpx.Client(timeout=20.0) as client:
        while page <= 10:
            r = client.get(
                f"https://api.github.com/repos/{meta.owner}/{meta.repo_name}/pulls/{pr_number}/files",
                headers=headers,
                params={"per_page": 100, "page": page},
            )
            if r.status_code >= 400:
                logger.warning("github pr files HTTP %s pr=%s", r.status_code, pr_number)
                break
            batch = r.json()
            if not isinstance(batch, list) or not batch:
                break
            for row in batch:
                fn = str(row.get("filename") or "").strip()
                if fn:
                    paths.append(fn)
            if len(batch) < 100:
                break
            page += 1
    return list(dict.fromkeys(paths))


def gitlab_mr_changed_files(
    *,
    clone_url: str,
    mr_iid: int,
    token: str | None,
    gitlab_base: str = "https://gitlab.com",
) -> list[str]:
    meta = parse_clone_url_meta(clone_url, "gitlab")
    if not meta:
        return []
    enc = urllib.parse.quote(meta.full_name, safe="")
    headers = {"PRIVATE-TOKEN": token.strip()} if token else {}
    paths: list[str] = []
    with httpx.Client(timeout=20.0) as client:
        r = client.get(
            f"{gitlab_base.rstrip('/')}/api/v4/projects/{enc}/merge_requests/{mr_iid}/changes",
            headers=headers,
        )
        if r.status_code >= 400:
            logger.warning("gitlab mr changes HTTP %s iid=%s", r.status_code, mr_iid)
            return []
        data = r.json()
        for ch in data.get("changes") or []:
            for key in ("new_path", "old_path"):
                p = str(ch.get(key) or "").strip()
                if p:
                    paths.append(p)
    return list(dict.fromkeys(paths))