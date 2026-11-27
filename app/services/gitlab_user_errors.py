"""私有化 GitLab 异常 → 界面友好文案（第四节规范）。"""

from __future__ import annotations

from app.services.git_secrets import redact_secrets_in_text


def format_gitlab_connection_error(base_url: str) -> str:
    base = (base_url or "GitLab").strip()
    return f"无法连接到 GitLab 服务器（{base}），请确认网络连通性或服务端口是否正确"


def format_gitlab_ssl_error() -> str:
    return "目标 GitLab 启用了自签名 HTTPS 证书，请勾选「跳过 SSL 证书校验」后重试"


def format_gitlab_forbidden_error() -> str:
    return (
        "仓库访问被拒绝（403），请确认当前账号拥有该私有仓库权限，"
        "或填写具有 read_api / read_repository 权限的独立 Token"
    )


def format_gitlab_not_found_error(branch: str | None) -> str:
    br = (branch or "main").strip() or "main"
    return f"未找到目标项目（404），请检查仓库地址拼写及分支名称（当前探测分支：{br}）"


def map_git_failure_message(
    hint: str,
    *,
    base_url: str | None = None,
    branch: str | None = None,
    ssl_verify: bool = True,
) -> str:
    text = redact_secrets_in_text(hint or "")
    lower = text.lower()
    if (
        "certificate_verify_failed" in lower
        or "ssl: certificate" in lower
        or "ssl certificate problem" in lower
        or "self signed certificate" in lower
    ):
        return format_gitlab_ssl_error()
    if not ssl_verify and "ssl" in lower:
        return format_gitlab_ssl_error()
    if "could not resolve host" in lower or "failed to connect" in lower or "connection refused" in lower:
        return format_gitlab_connection_error(base_url or "GitLab")
    if "timed out" in lower or "timeout" in lower:
        return format_gitlab_connection_error(base_url or "GitLab")
    if "401" in text or "403" in text or "authentication" in lower or "access denied" in lower:
        return format_gitlab_forbidden_error()
    if "404" in text or "not found" in lower or "repository not found" in lower:
        return format_gitlab_not_found_error(branch)
    return redact_secrets_in_text(text.strip()[:320] if text else "Git 操作失败")