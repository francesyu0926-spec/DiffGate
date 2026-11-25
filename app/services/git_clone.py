import os
import shutil
import stat
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote, urlparse, urlunparse

from git import Repo

from app.config import get_settings
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


def _harden_ssh_key_file(key_path: str) -> None:
    """OpenSSH on Windows rejects keys with inherited ACLs (libcrypto load error)."""
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    if os.name != "nt":
        return
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if not user:
        return
    subprocess.run(
        ["icacls", key_path, "/inheritance:r", "/grant:r", f"{user}:R"],
        capture_output=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _normalize_ssh_private_key(raw: str) -> str:
    text = raw.strip().replace("\r\n", "\n").replace("\r", "\n")
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def _write_ephemeral_ssh_key(repo: Repository) -> Path:
    normalized_key = _normalize_ssh_private_key(repo.ssh_private_key or "")
    keys_dir = (Path(get_settings().repo_clone_root).resolve().parent / "ssh_keys").resolve()
    keys_dir.mkdir(parents=True, exist_ok=True)
    key_path_obj = keys_dir / f"{repo.id}.{uuid.uuid4().hex}.key"
    key_path_obj.write_text(normalized_key, encoding="utf-8", newline="\n")
    _harden_ssh_key_file(str(key_path_obj))
    return key_path_obj


def git_ssh_command_from_path(key_path: Path | str) -> str:
    return f'ssh -i "{key_path}" -o StrictHostKeyChecking=no -o IdentitiesOnly=yes'


@contextmanager
def git_ssh_process_env(ssh_cmd: str | None) -> Iterator[None]:
    """Ensure child git/ssh processes see GIT_SSH_COMMAND (Windows-friendly)."""
    if not ssh_cmd:
        yield
        return
    prev = os.environ.get("GIT_SSH_COMMAND")
    os.environ["GIT_SSH_COMMAND"] = ssh_cmd
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("GIT_SSH_COMMAND", None)
        else:
            os.environ["GIT_SSH_COMMAND"] = prev


@contextmanager
def git_ssh_command_for_repo(repo: Repository | None) -> Iterator[str | None]:
    """Yield GIT_SSH_COMMAND value; cleans up ephemeral key file on exit."""
    key_path: Path | None = None
    try:
        if repo and (repo.auth_method or "") == "ssh" and (repo.ssh_private_key or "").strip():
            key_path = _write_ephemeral_ssh_key(repo)
            yield git_ssh_command_from_path(key_path)
        else:
            yield None
    finally:
        if key_path is not None:
            try:
                key_path.unlink(missing_ok=True)
            except OSError:
                pass


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
    clone_url = (repo.clone_url or "").strip()
    needs_ssh = clone_url.startswith("git@") or clone_url.startswith("ssh://")
    if method == "ssh" and not (repo.ssh_private_key or "").strip():
        raise ValueError("认证方式为 SSH，但尚未保存私钥。请编辑仓库，粘贴私钥并保存后再索引。")
    if needs_ssh and not (repo.ssh_private_key or "").strip() and method != "token":
        raise ValueError(
            "Clone URL 为 SSH 格式，需要配置 SSH 私钥：编辑仓库 → 认证选「SSH 私钥」→ 粘贴私钥 → 保存。"
        )

    if method == "ssh" and repo.ssh_private_key:
        with git_ssh_command_for_repo(repo) as ssh_cmd:
            assert ssh_cmd is not None
            env = os.environ.copy()
            env["GIT_SSH_COMMAND"] = ssh_cmd
            url = repo.clone_url
            if url.startswith("https://"):
                parsed = urlparse(url)
                path = parsed.path.strip("/").removesuffix(".git")
                url = f"git@{parsed.hostname}:{path}.git"
            return Repo.clone_from(url, str(dest), env=env, **clone_kwargs)

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