import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Repository


def ensure_registered(
    db: Session,
    *,
    provider: str,
    full_name: str,
    clone_url: str,
    default_branch: str = "main",
) -> Repository | None:
    """Webhook 首次见到的仓库自动登记；已禁用或未开 Webhook 的仓库返回 None。"""
    repo = db.scalar(select(Repository).where(Repository.full_name == full_name))
    if repo is None:
        repo = Repository(
            id=str(uuid.uuid4()),
            full_name=full_name,
            provider=provider,
            clone_url=clone_url,
            default_branch=default_branch or "main",
            enabled=True,
            webhook_enabled=True,
        )
        db.add(repo)
        db.commit()
        db.refresh(repo)
        return repo

    if not repo.enabled or not repo.webhook_enabled:
        return None
    if repo.clone_url != clone_url:
        repo.clone_url = clone_url
        db.commit()
    return repo