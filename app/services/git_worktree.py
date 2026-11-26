"""按 AnalysisJob 隔离 git worktree 沙箱，避免多分支并发 checkout 冲突。"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from git import Repo
from git.exc import BadName, GitCommandError

from app.config import get_settings

logger = logging.getLogger(__name__)

_WORKTREE_ONLY_PATH = re.compile(
    r"^[A-Za-z]:\\.*[/\\]worktrees[/\\][0-9a-fA-F-]{8,}[-0-9a-fA-F]{0,40}\s*$"
)


def git_fetch_user_message(exc: GitCommandError, *, context: str = "拉取提交") -> str:
    stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
    if "Permission denied" in stderr or "publickey" in stderr:
        return f"{context}失败：SSH 公钥认证被拒绝。请在「仓库管理」配置 SSH 私钥或 HTTPS Token。"
    if "Could not read from remote repository" in stderr:
        return f"{context}失败：无法访问远程仓库。请检查 Clone 地址与凭据。"
    if "fatal: invalid" in stderr.lower() or "could not find" in stderr.lower():
        return f"{context}失败：远程不存在该提交或本地浅克隆未包含该对象。"
    brief = stderr.strip().splitlines()[-1] if stderr.strip() else str(exc)
    return f"{context}失败：{brief}"


def ensure_commit_in_repo(repo: Repo, sha: str) -> None:
    """确保 base/head 对象在本地可解析（浅克隆需按 SHA fetch）。"""
    try:
        repo.commit(sha)
        return
    except (BadName, ValueError):
        pass
    try:
        repo.git.fetch("origin", sha)
    except GitCommandError as exc:
        raise RuntimeError(git_fetch_user_message(exc)) from exc
    try:
        repo.commit(sha)
    except (BadName, ValueError) as exc:
        raise RuntimeError(
            f"本地克隆仍缺少提交 {sha[:8]}。请在仓库管理确认 Git 凭据后重试分析。"
        ) from exc


def worktree_root() -> Path:
    root = (Path(get_settings().local_data_dir).resolve() / "worktrees").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def prepare_job_worktree(main_repo_dir: Path, job_id: str, head_sha: str) -> Path:
    """在主克隆上挂载独立 worktree 并 checkout head_sha。"""
    main_repo_dir = main_repo_dir.resolve()
    wt_path = (worktree_root() / job_id).resolve()
    if wt_path.exists():
        remove_job_worktree(job_id, main_repo_dir)
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    repo = Repo(str(main_repo_dir))
    ensure_commit_in_repo(repo, head_sha)
    # 必须使用绝对路径：相对路径会相对主克隆目录创建，导致返回路径不存在
    try:
        repo.git.worktree("add", "--detach", str(wt_path), head_sha)
    except GitCommandError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
        if wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)
        if "invalid reference" in stderr.lower():
            raise RuntimeError(
                f"无法检出提交 {head_sha[:8]} 到分析沙箱。请确认 Git 凭据并在仓库管理同步/重建索引后重新分析。"
            ) from exc
        raise RuntimeError(git_fetch_user_message(exc, context="创建分析沙箱")) from exc
    if not wt_path.is_dir():
        raise RuntimeError(
            f"分析沙箱 worktree 未创建成功（{wt_path.name}）。请重试分析；若反复出现请重启 API 服务。"
        )
    return wt_path


def is_worktree_path_only_error(message: str) -> bool:
    msg = message.strip()
    return bool(_WORKTREE_ONLY_PATH.match(msg))


def remove_job_worktree(job_id: str, main_repo_dir: Path | None = None) -> None:
    wt_path = (worktree_root() / job_id).resolve()
    if main_repo_dir:
        legacy = (main_repo_dir.resolve() / "data" / "worktrees" / job_id).resolve()
        if legacy.is_dir() and not wt_path.is_dir():
            wt_path = legacy
    if not wt_path.exists():
        return
    try:
        if main_repo_dir and (main_repo_dir / ".git").exists():
            Repo(str(main_repo_dir)).git.worktree("remove", "--force", str(wt_path))
    except Exception as exc:
        logger.debug("worktree remove via git failed: %s", exc)
    if wt_path.exists():
        shutil.rmtree(wt_path, ignore_errors=True)
    try:
        if main_repo_dir:
            Repo(str(main_repo_dir)).git.worktree("prune")
    except Exception:
        pass