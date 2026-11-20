import os
import tempfile
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from git import Repo

from app.db.models import Repository


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

    url = repo.clone_url
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