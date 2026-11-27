"""POST /repositories/branches — 仓库分支探测 API（async 入口）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.api.schemas import RepositoryBranchesIn, RepositoryBranchesOut
from app.db.models import TestSuite
from app.db.session import get_db
from app.services.auth_session import bearer_token_from_header
from app.services.repo_branch_detect import detect_repository_branches_async

router = APIRouter()


@router.post("/branches", response_model=RepositoryBranchesOut)
async def detect_repository_branches_endpoint(
    req: RepositoryBranchesIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
) -> dict:
    """
    分支探测管线：本地 git → GitHub/GitLab API（并行）→ git ls-remote --symref。
    总超时 8s；失败时返回 success=false 与 error_message（便于前端 freeSolo）。

    安全与稳定性：
    - GIT_TERMINAL_PROMPT=0，避免无凭据时 git 挂死等待交互；
    - error_message 脱敏（明文 token + URL 内嵌凭据 → ***）；
    - default_branch 置顶且 is_default=true。
    """
    bearer = bearer_token_from_header(authorization)
    suite = db.get(TestSuite, req.test_suite_id) if req.test_suite_id else None
    return await detect_repository_branches_async(
        db,
        clone_url=req.clone_url,
        credential_mode=req.credential_mode,
        access_token=req.access_token,
        ssh_private_key=req.ssh_private_key,
        verify_ssl=req.verify_ssl,
        linked_repo_id=req.linked_repo_id,
        bearer_session_token=bearer,
        suite=suite,
    )