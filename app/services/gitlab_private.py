"""私有化 GitLab：路径编码、Webhook 指纹、SSL 策略。"""

from __future__ import annotations

import ipaddress
import re
import urllib.parse

from app.config import get_settings
from app.services.repo_detect_parse import CloneUrlMeta, parse_clone_url_meta


def encode_gitlab_project_path(project_path: str) -> str:
    """GitLab REST API：多级群组路径须将 `/` 编码为 `%2F`。"""
    path = (project_path or "").strip().strip("/")
    if not path:
        return ""
    return urllib.parse.quote(path, safe="")


def encode_gitlab_project_from_meta(meta: CloneUrlMeta) -> str:
    return encode_gitlab_project_path(meta.project_path or meta.full_name)


def webhook_core_fingerprint(clone_url: str | None) -> str | None:
    """Webhook 匹配用：主机名（不含端口）+ 全项目路径，忽略 http/https。"""
    raw = (clone_url or "").strip()
    if not raw:
        return None
    meta = parse_clone_url_meta(raw, None)
    if not meta or meta.provider == "local" or not meta.host:
        return None
    path = (meta.project_path or meta.full_name or "").strip("/").lower()
    if not path:
        return None
    host = meta.host.lower()
    return f"{host}/{path}"


def normalized_clone_url(clone_url: str | None) -> str | None:
    """与 webhook_core_fingerprint 等价，供匹配模块引用。"""
    return webhook_core_fingerprint(clone_url)


def _is_private_ip(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def is_internal_git_host(clone_url: str) -> bool:
    meta = parse_clone_url_meta(clone_url, None)
    host = (meta.host if meta else "") or ""
    if not host:
        return False
    if _is_private_ip(host):
        return True
    if host in ("localhost", "127.0.0.1"):
        return True
    if re.search(r"\.(local|internal|corp|lan)$", host, re.I):
        return True
    if meta and meta.base_url:
        try:
            from urllib.parse import urlparse

            p = urlparse(meta.base_url)
            if p.port and p.port not in (80, 443):
                return True
        except Exception:
            pass
    return False


def resolve_git_ssl_verify(clone_url: str, skip_ssl_verify: bool | None = None) -> bool:
    """返回 httpx/git 用的 verify 标志（True=校验证书）。"""
    if skip_ssl_verify is True:
        return False
    if skip_ssl_verify is False:
        return True
    settings = get_settings()
    if getattr(settings, "git_skip_ssl_verify_internal", True) and is_internal_git_host(clone_url):
        return False
    return True


def gitlab_api_base(meta: CloneUrlMeta, fallback: str = "https://gitlab.com") -> str:
    return (meta.base_url or fallback).rstrip("/")