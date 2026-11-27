"""远程/本地分支枚举与「功能分支 vs 基准分支」三点 diff 的 SHA 解析。"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from git import Repo
from git.exc import BadName, GitCommandError

from app.db.models import Repository
from app.services.git_clone import (
    clone_repository,
    clear_clone_dest,
    git_ssh_command_for_repo,
    inject_access_token,
    _normalize_local_clone_url,
)
from app.services.repo_index import _repo_dir

_BRANCH_CACHE: dict[str, tuple[float, list[str]]] = {}
_BRANCH_CACHE_TTL_SEC = 30


def _effective_ls_remote_url(repo: Repository) -> str:
    url = (repo.clone_url or "").strip()
    if repo.provider == "local":
        url = _normalize_local_clone_url(url)
        return url
    method = repo.auth_method or "none"
    if method == "token" and repo.access_token:
        return inject_access_token(url, repo.access_token, repo.provider)
    return url


def _run_git(args: list[str], *, env: dict | None = None) -> str:
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise GitCommandError(args[0], proc.returncode, err)
    return proc.stdout or ""


def list_repository_branches(repo: Repository) -> list[str]:
    """列出分支名（短名）。30 秒缓存；本地仓走本地 ref，远端走 ls-remote。"""
    now = time.time()
    cached = _BRANCH_CACHE.get(repo.id)
    if cached and now - cached[0] < _BRANCH_CACHE_TTL_SEC:
        return list(cached[1])

    names: set[str] = set()
    if repo.provider == "local":
        repo_dir = _repo_dir(repo.full_name).resolve()
        if not (repo_dir / ".git").is_dir():
            clear_clone_dest(repo_dir)
            clone_repository(repo, repo_dir, branch=repo.default_branch, depth=1)
        git = Repo(str(repo_dir))
        for head in git.heads:
            names.add(head.name)
        for remote in git.remotes:
            for ref in remote.refs:
                short = ref.name.split("/", 1)[-1] if "/" in ref.name else ref.name
                if short != "HEAD":
                    names.add(short)
    else:
        url = _effective_ls_remote_url(repo)
        with git_ssh_command_for_repo(repo) as ssh_cmd:
            env = None
            if ssh_cmd:
                import os

                env = os.environ.copy()
                env["GIT_SSH_COMMAND"] = ssh_cmd
            out = _run_git(["git", "ls-remote", "--heads", url], env=env)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            ref = parts[1]
            if ref.startswith("refs/heads/"):
                names.add(ref[len("refs/heads/") :])

    if repo.default_branch:
        names.add(repo.default_branch)
    result = sorted(names, key=str.lower)
    _BRANCH_CACHE[repo.id] = (now, result)
    return result


def _ensure_git_repo(repo: Repository, *, fetch: bool = False) -> Repo:
    repo_dir = _repo_dir(repo.full_name).resolve()
    if not (repo_dir / ".git").is_dir():
        clear_clone_dest(repo_dir)
        clone_repository(repo, repo_dir, branch=repo.default_branch, depth=80)
    git = Repo(str(repo_dir))
    if fetch:
        with git_ssh_command_for_repo(repo) as ssh_cmd:
            kwargs = {}
            if ssh_cmd:
                import os

                kwargs["env"] = {**os.environ, "GIT_SSH_COMMAND": ssh_cmd}
            for remote in git.remotes:
                try:
                    remote.fetch(**kwargs)
                except GitCommandError:
                    pass
    return git


def _resolve_branch_sha_via_ls_remote(repo: Repository, branch: str) -> str:
    """远程分支未检出到本地时，用 ls-remote 解析 tip SHA。"""
    name = branch.strip()
    if not name:
        raise ValueError("分支名不能为空")
    if repo.provider == "local":
        raise ValueError(f"本地仓库无分支「{branch}」")
    url = _effective_ls_remote_url(repo)
    ref = name if name.startswith("refs/") else f"refs/heads/{name}"
    with git_ssh_command_for_repo(repo) as ssh_cmd:
        env = None
        if ssh_cmd:
            import os

            env = {**os.environ, "GIT_SSH_COMMAND": ssh_cmd}
        out = _run_git(["git", "ls-remote", url, ref], env=env)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 1 and len(parts[0]) >= 8:
            return parts[0].strip()
    raise ValueError(f"远程不存在分支「{branch}」")


def _resolve_branch_sha(git: Repo, branch: str, repo: Repository | None = None) -> str:
    name = branch.strip()
    if not name:
        raise ValueError("分支名不能为空")
    candidates: list[str] = []
    if name.startswith("refs/"):
        candidates.append(name)
    else:
        candidates.extend(
            [
                name,
                f"refs/heads/{name}",
            ]
        )
        for remote in git.remotes:
            candidates.append(f"refs/remotes/{remote.name}/{name}")
            candidates.append(f"{remote.name}/{name}")
    seen: set[str] = set()
    last_err: Exception | None = None
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        try:
            sha = git.git.rev_parse("--verify", f"{cand}^{{commit}}")
            if sha:
                return sha.strip()
        except GitCommandError as exc:
            last_err = exc
        except (BadName, ValueError, TypeError) as exc:
            last_err = exc
        try:
            return git.commit(cand).hexsha
        except (BadName, ValueError, TypeError) as exc:
            last_err = exc
    if repo is not None and repo.provider != "local":
        try:
            return _resolve_branch_sha_via_ls_remote(repo, name)
        except Exception as exc:
            last_err = exc
    raise ValueError(f"无法解析分支「{branch}」") from last_err


def resolve_analysis_shas(
    repo: Repository,
    *,
    branch: str | None = None,
    base_branch: str | None = None,
) -> tuple[str, str, str]:
    """
    返回 (base_sha, head_sha, ref)。

    - 默认：HEAD 与其父提交（与历史行为一致）。
    - 指定 branch + base_branch：head=分支 tip，base=merge-base(base_branch, head)（等同 git diff A...B）。
    - 仅指定 branch：该分支 tip 与其父提交。
    """
    target_branch = (branch or repo.default_branch or "main").strip()
    git = _ensure_git_repo(repo, fetch=True)
    head_sha = _resolve_branch_sha(git, target_branch, repo)

    ref = target_branch if target_branch.startswith("refs/") else f"refs/heads/{target_branch}"

    if base_branch and base_branch.strip():
        base_tip = _resolve_branch_sha(git, base_branch.strip(), repo)
        try:
            merge = git.merge_base(base_tip, head_sha)
            base_sha = merge[0].hexsha if merge else base_tip
        except (GitCommandError, ValueError, TypeError, BadName):
            # 本地无双方对象时仍用 tips 作为 diff 端点（分析 runner 会 fetch 目标提交）
            base_sha = base_tip
        return base_sha, head_sha, ref

    head_commit = git.commit(head_sha)
    parents = head_commit.parents
    base_sha = parents[0].hexsha if parents else head_sha
    return base_sha, head_sha, ref