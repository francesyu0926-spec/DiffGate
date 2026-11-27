"""Clone URL 归一化：HTTP / SSH 对齐为同一匹配键。"""

from __future__ import annotations

from app.services.gitlab_private import webhook_core_fingerprint
from app.services.repo_detect_parse import parse_clone_url_meta


def clone_url_repo_slug(clone_url: str | None) -> str | None:
    """剥离协议 / git@ 主机头，仅保留组织路径 owner/repo。"""
    raw = (clone_url or "").strip()
    if not raw:
        return None
    meta = parse_clone_url_meta(raw, None)
    if meta and meta.full_name:
        return meta.full_name.lower()
    return None


def clone_url_match_key(clone_url: str | None) -> str | None:
    raw = (clone_url or "").strip()
    if not raw:
        return None
    meta = parse_clone_url_meta(raw, None)
    if meta and meta.full_name:
        return f"{meta.provider}:{meta.full_name}".lower()
    return raw.lower().rstrip("/").removesuffix(".git")


def collect_incoming_clone_keys(*urls: str | None) -> tuple[set[str], set[str], set[str]]:
    """HTTP + SSH 等多 URL 的匹配键、owner/repo slug、Webhook 核心指纹。"""
    keys: set[str] = set()
    slugs: set[str] = set()
    fingerprints: set[str] = set()
    for u in urls:
        if not u:
            continue
        k = clone_url_match_key(u)
        if k:
            keys.add(k)
        slug = clone_url_repo_slug(u)
        if slug:
            slugs.add(slug)
        fp = webhook_core_fingerprint(u)
        if fp:
            fingerprints.add(fp)
    return keys, slugs, fingerprints


def platform_full_name_base(full_name: str) -> str:
    s = (full_name or "").strip()
    if " (" in s:
        return s.split(" (", 1)[0].strip()
    return s


def record_matches_platform_repo(record_full_name: str, platform_full_name: str) -> bool:
    pf = platform_full_name.strip()
    if not pf:
        return False
    base = platform_full_name_base(record_full_name)
    return base == pf or record_full_name.strip() == pf