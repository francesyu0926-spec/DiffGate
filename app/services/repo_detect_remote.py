"""GitHub / GitLab 零克隆树查询（深度约 2 层）。"""

from __future__ import annotations

import base64
import urllib.parse
from typing import Any

import httpx

from app.services.gitlab_private import (
    encode_gitlab_project_from_meta,
    gitlab_api_base,
    resolve_git_ssl_verify,
)
from app.services.repo_detect_parse import CloneUrlMeta


def _github_headers(token: str | None) -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token.strip()}"
    return h


def _gitlab_headers(token: str | None) -> dict[str, str]:
    h: dict[str, str] = {}
    if token:
        h["PRIVATE-TOKEN"] = token.strip()
    return h


def resolve_default_branch_github(meta: CloneUrlMeta, token: str | None, branch: str | None) -> str:
    if branch:
        return branch
    with httpx.Client(timeout=8.0) as client:
        r = client.get(
            f"https://api.github.com/repos/{meta.owner}/{meta.repo_name}",
            headers=_github_headers(token),
        )
    if r.status_code >= 400:
        return "main"
    return str(r.json().get("default_branch") or "main")


def resolve_default_branch_gitlab(
    meta: CloneUrlMeta,
    token: str | None,
    branch: str | None,
    base_url: str | None = None,
    *,
    clone_url: str | None = None,
    skip_ssl_verify: bool | None = None,
) -> str:
    if branch:
        return branch
    api_base = (base_url or gitlab_api_base(meta)).rstrip("/")
    enc = encode_gitlab_project_from_meta(meta)
    verify = resolve_git_ssl_verify(clone_url or api_base, skip_ssl_verify)
    with httpx.Client(timeout=8.0, verify=verify) as client:
        r = client.get(f"{api_base}/api/v4/projects/{enc}", headers=_gitlab_headers(token))
    if r.status_code >= 400:
        return "main"
    return str(r.json().get("default_branch") or "main")


def _decode_github_content(node: dict[str, Any]) -> str | None:
    if node.get("encoding") == "base64" and node.get("content"):
        try:
            return base64.b64decode(node["content"]).decode("utf-8", errors="replace")
        except Exception:
            return None
    return None


def fetch_github_tree(
    meta: CloneUrlMeta, token: str | None, branch: str | None
) -> tuple[set[str], dict[str, str], str]:
    branch = resolve_default_branch_github(meta, token, branch)
    paths: set[str] = set()
    contents: dict[str, str] = {}
    headers = _github_headers(token)
    read_names = {
        "package.json",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "requirements.txt",
        "pyproject.toml",
        "setup.py",
        "pipfile",
    }

    with httpx.Client(timeout=12.0) as client:
        r = client.get(
            f"https://api.github.com/repos/{meta.owner}/{meta.repo_name}/contents",
            headers=headers,
            params={"ref": branch},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"GitHub API HTTP {r.status_code}")
        root_items = r.json()
        if not isinstance(root_items, list):
            raise RuntimeError("GitHub contents 响应异常")
        for item in root_items:
            name = str(item.get("name") or "")
            if not name or name.startswith("."):
                continue
            paths.add(name)
            if item.get("type") == "file" and name.lower() in read_names:
                cr = client.get(
                    f"https://api.github.com/repos/{meta.owner}/{meta.repo_name}/contents/{urllib.parse.quote(name)}",
                    headers=headers,
                    params={"ref": branch},
                )
                if cr.status_code < 400:
                    text = _decode_github_content(cr.json())
                    if text:
                        contents[name] = text
            elif item.get("type") == "dir" and name in ("backend", "server", "frontend", "web", "apps"):
                sub_r = client.get(
                    f"https://api.github.com/repos/{meta.owner}/{meta.repo_name}/contents/{urllib.parse.quote(name)}",
                    headers=headers,
                    params={"ref": branch},
                )
                if sub_r.status_code >= 400:
                    continue
                sub_items = sub_r.json()
                if not isinstance(sub_items, list):
                    continue
                for sub in sub_items:
                    sname = str(sub.get("name") or "")
                    if not sname or sname.startswith("."):
                        continue
                    rel = f"{name}/{sname}"
                    paths.add(rel)
                    if sub.get("type") == "file" and sname.lower() in read_names:
                        cr = client.get(
                            f"https://api.github.com/repos/{meta.owner}/{meta.repo_name}/contents/{name}/{urllib.parse.quote(sname)}",
                            headers=headers,
                            params={"ref": branch},
                        )
                        if cr.status_code < 400:
                            text = _decode_github_content(cr.json())
                            if text:
                                contents[rel] = text
    return paths, contents, branch


def fetch_gitlab_tree(
    meta: CloneUrlMeta,
    token: str | None,
    branch: str | None,
    base_url: str | None = None,
    *,
    clone_url: str | None = None,
    skip_ssl_verify: bool | None = None,
) -> tuple[set[str], dict[str, str], str]:
    api_base = (base_url or gitlab_api_base(meta)).rstrip("/")
    branch = resolve_default_branch_gitlab(
        meta,
        token,
        branch,
        api_base,
        clone_url=clone_url,
        skip_ssl_verify=skip_ssl_verify,
    )
    enc = encode_gitlab_project_from_meta(meta)
    verify = resolve_git_ssl_verify(clone_url or api_base, skip_ssl_verify)
    paths: set[str] = set()
    contents: dict[str, str] = {}
    headers = _gitlab_headers(token)
    read_names = {
        "package.json",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "requirements.txt",
        "pyproject.toml",
        "setup.py",
        "pipfile",
    }

    with httpx.Client(timeout=12.0, verify=verify) as client:
        r = client.get(
            f"{api_base}/api/v4/projects/{enc}/repository/tree",
            headers=headers,
            params={"ref": branch, "recursive": "false", "per_page": "100"},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"GitLab API HTTP {r.status_code}")
        level1 = r.json()
        for item in level1:
            p = str(item.get("path") or "")
            if not p or p.startswith("."):
                continue
            paths.add(p)
        for prefix in ("backend", "server", "frontend", "web", "apps"):
            sr = client.get(
                f"{api_base}/api/v4/projects/{enc}/repository/tree",
                headers=headers,
                params={"ref": branch, "path": prefix, "per_page": "100"},
            )
            if sr.status_code >= 400:
                continue
            for item in sr.json():
                p = str(item.get("path") or "")
                if p:
                    paths.add(p)
                name = str(item.get("name") or "")
                if item.get("type") == "blob" and name.lower() in read_names:
                    raw_r = client.get(
                        f"{api_base}/api/v4/projects/{enc}/repository/files/{urllib.parse.quote(p, safe='')}/raw",
                        headers=headers,
                        params={"ref": branch},
                    )
                    if raw_r.status_code < 400 and len(raw_r.content) <= 120_000:
                        contents[p] = raw_r.text

        for p in list(paths):
            base = p.split("/")[-1].lower()
            if base in read_names and p not in contents and "/" not in p:
                raw_r = client.get(
                    f"{api_base}/api/v4/projects/{enc}/repository/files/{urllib.parse.quote(p, safe='')}/raw",
                    headers=headers,
                    params={"ref": branch},
                )
                if raw_r.status_code < 400 and len(raw_r.content) <= 120_000:
                    contents[p] = raw_r.text

    return paths, contents, branch