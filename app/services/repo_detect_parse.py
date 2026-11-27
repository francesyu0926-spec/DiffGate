"""从 Clone URL 解析平台、传输方式与 owner/repo。

优先级（与产品说明一致）：
1. 本地路径 local — `/`、`./`、`file://`、Windows 盘符等
2. SSH — `git@host:group/project.git`、`ssh://`
3. HTTP(S) — 含内网 IP、自定义端口
4. 平台推断 — github.com / GitHub Enterprise → github；含 gitlab 或其余域名 → gitlab（私有化默认）
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class CloneUrlMeta:
    provider: str
    owner: str
    repo_name: str
    full_name: str
    transport: str = "http"
    host: str | None = None
    base_url: str | None = None
    project_path: str | None = None


def _strip_url(raw: str) -> str:
    return raw.strip().strip('"').strip("'")


def is_local_clone_url(raw: str) -> bool:
    raw = _strip_url(raw)
    if raw.startswith("file://"):
        return True
    if raw.startswith(("./", "../")):
        return True
    if raw.startswith("/"):
        return True
    if re.match(r"^[A-Za-z]:[/\\]", raw):
        return True
    if raw.startswith(("http://", "https://", "git@", "ssh://")):
        return False
    if "/" in raw or "\\" in raw:
        return True
    return False


def is_ssh_clone_url(raw: str) -> bool:
    raw = _strip_url(raw)
    return raw.startswith("git@") or raw.startswith("ssh://")


def is_http_clone_url(raw: str) -> bool:
    raw = _strip_url(raw)
    return raw.startswith("http://") or raw.startswith("https://")


def infer_provider_from_host(host: str, source_type: str | None = None) -> str:
    if source_type in ("github", "gitlab"):
        return source_type
    h = (host or "").lower()
    if h == "github.com" or re.match(r"^github\..+\.com$", h):
        return "github"
    if "gitlab" in h:
        return "gitlab"
    return "gitlab"


def _parse_project_path(path: str) -> tuple[str, str, str] | None:
    path = path.strip("/").removesuffix(".git")
    if not path or "/" not in path:
        return None
    owner, repo = path.rsplit("/", 1)
    return owner, repo, path


def _meta_local(raw: str) -> CloneUrlMeta:
    cleaned = _strip_url(raw).replace("file://", "")
    name = Path(cleaned).name or "local-repo"
    if name.lower().endswith(".git"):
        name = name[:-4]
    return CloneUrlMeta(
        "local",
        "",
        name,
        name,
        transport="local",
        host=None,
        base_url=None,
        project_path=cleaned,
    )


def _meta_ssh(raw: str, source_type: str | None) -> CloneUrlMeta | None:
    raw = _strip_url(raw)
    host = ""
    project_path = ""
    if raw.startswith("git@"):
        if ":" not in raw:
            return None
        host_part = raw.split("@", 1)[1].split(":", 1)[0]
        host = host_part.lower()
        project_path = raw.split(":", 1)[-1].removesuffix(".git")
    elif raw.startswith("ssh://"):
        u = urlparse(raw)
        host = (u.hostname or "").lower()
        project_path = (u.path or "").strip("/").removesuffix(".git")
    else:
        return None
    parts = _parse_project_path(project_path)
    if not parts:
        return None
    owner, repo, full_path = parts
    provider = infer_provider_from_host(host, source_type)
    return CloneUrlMeta(
        provider,
        owner,
        repo,
        full_path,
        transport="ssh",
        host=host or None,
        base_url=None,
        project_path=project_path,
    )


def _meta_http(raw: str, source_type: str | None) -> CloneUrlMeta | None:
    try:
        u = urlparse(_strip_url(raw))
    except Exception:
        return None
    if u.scheme not in ("http", "https"):
        return None
    host = (u.hostname or "").lower()
    port = u.port
    base_url = f"{u.scheme}://{u.hostname}"
    if port:
        base_url += f":{port}"
    parts = _parse_project_path(u.path or "")
    if not parts:
        return None
    owner, repo, full_path = parts
    provider = infer_provider_from_host(host, source_type)
    project_path = (u.path or "").strip("/").removesuffix(".git")
    return CloneUrlMeta(
        provider,
        owner,
        repo,
        full_path,
        transport="http",
        host=host or None,
        base_url=base_url,
        project_path=project_path,
    )


def parse_clone_url_meta(clone_url: str, source_type: str | None = None) -> CloneUrlMeta | None:
    raw = _strip_url(clone_url)
    if not raw:
        return None

    forced = (source_type or "").lower()
    if forced == "local" or (is_local_clone_url(raw) and not is_ssh_clone_url(raw) and not is_http_clone_url(raw)):
        return _meta_local(raw)
    if is_ssh_clone_url(raw):
        return _meta_ssh(raw, source_type)
    if is_http_clone_url(raw):
        return _meta_http(raw, source_type)
    if forced == "local":
        return _meta_local(raw)
    return None


def validate_local_git_workspace(path_str: str) -> tuple[bool, str]:
    cleaned = _strip_url(path_str).replace("file://", "")
    p = Path(cleaned)
    if not p.exists():
        return False, f"本地路径不存在：{cleaned}"
    if not p.is_dir():
        return False, f"本地路径不是目录：{cleaned}"
    if (p / ".git").is_dir():
        return True, "本地 Git 仓库可访问"
    return True, "本地目录可访问（未检测到 .git，将直接扫描用例文件）"


def resolve_effective_provider(clone_url: str, source_type: str | None = None) -> str:
    meta = parse_clone_url_meta(clone_url, source_type)
    if not meta:
        return (source_type or "gitlab").lower()
    if meta.provider == "local":
        return "local"
    explicit = (source_type or "").lower()
    if explicit in ("github", "gitlab"):
        return explicit
    return meta.provider


def suggested_auth_for_meta(meta: CloneUrlMeta) -> str:
    if meta.provider == "local":
        return "none"
    if meta.transport == "ssh":
        return "ssh"
    return "token"


def classify_clone_url(clone_url: str, source_type: str | None = None) -> dict:
    meta = parse_clone_url_meta(clone_url, source_type)
    if not meta:
        return {
            "ok": False,
            "message": "无法识别的仓库地址，请使用 https、git@、ssh:// 或本地路径",
        }
    out: dict = {
        "ok": True,
        "provider": meta.provider,
        "transport": meta.transport,
        "full_name": meta.full_name,
        "host": meta.host,
        "base_url": meta.base_url,
        "project_path": meta.project_path,
        "suggested_auth": suggested_auth_for_meta(meta),
        "message": f"识别为 {meta.provider}（{meta.transport}）",
    }
    if meta.transport == "local":
        valid, msg = validate_local_git_workspace(clone_url)
        out["local_valid"] = valid
        if not valid:
            out["ok"] = False
        out["message"] = msg
    elif meta.transport == "ssh":
        out["message"] = f"SSH 地址，平台推断为 {meta.provider}；克隆请配置 SSH 私钥"
    elif meta.base_url:
        out["message"] = f"HTTPS 地址 {meta.base_url}，平台推断为 {meta.provider}"
    return out


def clone_url_meta_dict(meta: CloneUrlMeta) -> dict:
    return asdict(meta)