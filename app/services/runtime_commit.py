"""运行时 Commit SHA：CI / 探针与 AnalysisJob.head_sha 对齐。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def normalize_sha(sha: str | None) -> str:
    return (sha or "").strip().lower()


def sha_matches_target(running: str | None, target: str | None) -> bool:
    a = normalize_sha(running)
    b = normalize_sha(target)
    if not a or not b:
        return True
    return a == b or a.startswith(b) or b.startswith(a)


def resolve_running_commit_sha(repo_dir: Path | None = None) -> str | None:
    for key in (
        "DIFFGATE_RUNNING_COMMIT_SHA",
        "GIT_COMMIT",
        "CI_COMMIT_SHA",
        "GITHUB_SHA",
    ):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    if repo_dir is not None and repo_dir.is_dir():
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if proc.returncode == 0:
                return proc.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return None