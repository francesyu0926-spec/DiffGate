"""Git URL / 异常信息中的凭据脱敏。"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

_TOKEN_IN_URL = re.compile(
    r"(https?://)(?:oauth2|x-access-token|[^:@/]+):([^@]+)@",
    re.IGNORECASE,
)
_GIT_AT_CRED = re.compile(r"git@[^:]+:", re.IGNORECASE)


def redact_url_credentials(url: str) -> str:
    if not url:
        return url
    redacted = _TOKEN_IN_URL.sub(r"\1***@", url)
    return redacted


def redact_secrets_in_text(text: str) -> str:
    if not text:
        return text
    out = _TOKEN_IN_URL.sub(r"\1***@", text)
    for m in re.finditer(r"https?://[^\s'\"]+", out):
        seg = m.group(0)
        clean = redact_url_credentials(seg)
        if clean != seg:
            out = out.replace(seg, clean, 1)
    return out


def safe_url_for_log(url: str) -> str:
    try:
        u = urlparse(url)
        if u.username or u.password:
            host = u.hostname or ""
            if u.port:
                host = f"{host}:{u.port}"
            return urlunparse((u.scheme, host, u.path, u.params, u.query, u.fragment))
    except Exception:
        pass
    return redact_url_credentials(url)