import os
import shutil
import stat
import tempfile
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from git import Repo

from app.db.models import Repository


def _normalize_local_clone_url(clone_url: str) -> str:
    raw = clone_url.strip().strip('"').strip("'")
    if raw.startswith("file://"):
        raw = raw[7:]
    path = Path(raw)
    if path.is_dir():
        return str(path.resolve())
    return raw


def clear_clone_dest(dest: Path) -> None:
    """Delete an existing clone cache directory (read-only .git files on Windows)."""
    dest = dest.resolve()
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        return

    def _on_rm_error(func, path, _exc_info):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass

    shutil.rmtree(dest, onerror=_on_rm_error)
    if dest.exists():
        raise OSError(
            f"无法清空仓库缓存目录 {dest}（可能被占用），请关闭相关程序后重试"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)


def inject_access_token(clone_url: str, token: str, provider: str) -> str:
    parsed = urlparse(clone_url)
    if not parsed.scheme.startswith("http"):
        return clone_url
    user = "oauth2" if provider == "gitlab" else "x-access-token"
    token_enc = quote(token, safe="")
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    netloc = f"{user}:{token_enc}@{host}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def clone_repository(repo: Repository, dest: Path, **clone_kwargs) -> Repo:
    dest = Path(dest).resolve()
    if dest.exists():
        clear_clone_dest(dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
    method = repo.auth_method or "none"

    if method == "ssh" and repo.ssh_private_key:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".key", encoding="utf-8") as f:
            f.write(repo.ssh_private_key.strip())
            f.write("\n")
            key_path = f.name
        try:
            os.chmod(key_path, 0o600)
            env = os.environ.copy()
            env["GIT_SSH_COMMAND"] = f'ssh -i "{key_path}" -o StrictHostKeyChecking=no'
            url = repo.clone_url
            if url.startswith("https://"):
                parsed = urlparse(url)
                path = parsed.path.strip("/").removesuffix(".git")
                url = f"git@{parsed.hostname}:{path}.git"
            return Repo.clone_from(url, str(dest), env=env, **clone_kwargs)
        finally:
            try:
                os.unlink(key_path)
            except OSError:
                pass

    url = repo.clone_url.strip()
    if repo.provider == "local":
        url = _normalize_local_clone_url(url)
        local = Path(url)
        if not local.is_dir():
            raise FileNotFoundError(f"本地仓库路径不存在: {url}")
        if not (local / ".git").is_dir():
            raise ValueError(f"路径不是 Git 仓库（缺少 .git）: {url}")
        url = str(local.resolve())

    if method == "token" and repo.access_token:
        url = inject_access_token(url, repo.access_token, repo.provider)
    return Repo.clone_from(url, str(dest), **clone_kwargs)


def clone_or_fallback(
    repo: Repository | None,
    clone_url: str,
    dest: Path,
    provider: str,
    **clone_kwargs,
) -> Repo:
    if repo is not None:
        return clone_repository(repo, dest, **clone_kwargs)
    return Repo.clone_from(clone_url, str(dest), **clone_kwargs)