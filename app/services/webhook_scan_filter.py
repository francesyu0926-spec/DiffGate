"""Webhook：按 scan_root 过滤变更文件，避免 Monorepo 空跑。"""

from __future__ import annotations

# 仓根目录公共文件：不应触发 backend/frontend 等子目录 scan_root 的分析
_GLOBAL_ROOT_BASENAMES = frozenset(
    {
        ".editorconfig",
        ".env",
        ".env.example",
        ".env.local",
        ".env.sample",
        ".gitignore",
        ".gitattributes",
        ".dockerignore",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "readme.md",
        "license",
        "license.md",
        "makefile",
        "justfile",
        "jenkinsfile",
        "catalog-info.yaml",
        "renovate.json",
    }
)


def normalize_repo_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def is_repo_root_global_file(changed_path: str) -> bool:
    p = normalize_repo_path(changed_path)
    if not p or "/" in p:
        return False
    base = p.rsplit("/", 1)[-1].lower()
    if base in _GLOBAL_ROOT_BASENAMES:
        return True
    if base.endswith((".md", ".yml", ".yaml")) and "." not in base.rsplit(".", 1)[0]:
        return base.startswith(("readme", "changelog", "contributing"))
    return False


def path_under_scan_root(changed_path: str, scan_root: str) -> bool:
    root = normalize_repo_path((scan_root or ".").strip() or ".")
    p = normalize_repo_path(changed_path)
    if root in ("", "."):
        return True
    return p == root or p.startswith(root + "/")


def repo_hit_by_scan_root(changed_paths: list[str], scan_root: str) -> bool:
    """scan_root 为 . 时：changed_files 非空即命中；子目录需前缀匹配（含 removed）。"""
    root = (scan_root or ".").strip() or "."
    if not changed_paths:
        return False
    if root in (".", ""):
        return True
    return any(path_under_scan_root(p, scan_root) for p in changed_paths)


def path_filter_skip_reason(changed_paths: list[str], scan_root: str) -> str:
    root = normalize_scan_root(scan_root)
    if not changed_paths:
        return "empty_changed_files"
    if root in (".", ""):
        return "full_repo_miss"
    only_global = all(is_repo_root_global_file(p) for p in changed_paths)
    if only_global:
        return "skipped_global_root_only"
    if not any(path_under_scan_root(p, scan_root) for p in changed_paths):
        return "skipped_by_path_filter"
    return "hit"


def normalize_scan_root(scan_root: str | None) -> str:
    s = (scan_root or ".").strip() or "."
    return s.replace("\\", "/")


def any_change_in_scan_root(changed_paths: list[str], scan_root: str) -> bool:
    return repo_hit_by_scan_root(changed_paths, scan_root)


def github_push_changed_paths(payload: dict) -> list[str]:
    out: list[str] = []
    for c in payload.get("commits") or []:
        for key in ("added", "modified", "removed"):
            out.extend([str(p) for p in (c.get(key) or []) if p])
    head = payload.get("head_commit") or {}
    for key in ("added", "modified", "removed"):
        out.extend([str(p) for p in (head.get(key) or []) if p])
    return list(dict.fromkeys(out))


def gitlab_push_changed_paths(payload: dict) -> list[str]:
    out: list[str] = []
    for c in payload.get("commits") or []:
        out.extend([str(p) for p in (c.get("modified") or []) if p])
        out.extend([str(p) for p in (c.get("added") or []) if p])
        out.extend([str(p) for p in (c.get("removed") or []) if p])
    return list(dict.fromkeys(out))