import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import (
    TestSuiteBranchesIn,
    TestSuiteCreate,
    TestSuiteOut,
    TestSuitePreviewIn,
    TestSuitePreviewOut,
    TestSuiteProbeIn,
    TestSuiteUpdate,
)
from app.db.models import Repository, TestSuite
from app.db.session import get_db
from app.services.auth_session import bearer_token_from_header
from app.services.repo_branch_detect import list_suite_source_branches
from app.services.test_suite_preview import preview_suite_source
from app.services.test_suite_probe import probe_suite_source
from app.services.test_suite_sync import (
    _apply_source_fields,
    bind_repositories,
    linked_repository_ids,
    sync_test_suite,
)
from app.utils.time_format import as_utc_iso

router = APIRouter(prefix="/test-suites", tags=["test-suites"])


def _repo_count_by_slug(db: Session, slug: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Repository)
            .where(Repository.test_suite_id == slug)
        )
        or 0
    )


def _to_out(row: TestSuite, db: Session) -> dict:
    data = TestSuiteOut.model_validate(row, from_attributes=True).model_dump()
    data["token_configured"] = bool((row.access_token or "").strip())
    data["ssh_configured"] = bool((row.ssh_private_key or "").strip())
    data.pop("access_token", None)
    data.pop("ssh_private_key", None)
    data["repo_count"] = _repo_count_by_slug(db, row.slug)
    data["linked_repository_ids"] = linked_repository_ids(db, row.slug)
    data["created_at"] = as_utc_iso(row.created_at)
    data["updated_at"] = as_utc_iso(row.updated_at)
    data["last_synced_at"] = as_utc_iso(row.last_synced_at)
    return data


def _normalize_create(body: TestSuiteCreate) -> tuple[dict, list[str] | None]:
    data = body.model_dump()
    repo_ids = data.pop("repository_ids", None)
    data["slug"] = body.slug.strip().lower()
    data["name"] = body.name.strip()
    data["description"] = (body.description or "").strip() or None
    data["external_ref"] = (body.external_ref or "").strip() or None
    data["git_url"] = (body.git_url or "").strip() or None
    data["git_branch"] = (body.git_branch or "").strip() or None
    data["case_path"] = (body.case_path or "").strip() or None
    data["trigger_webhook_url"] = (body.trigger_webhook_url or "").strip() or None
    return data, repo_ids


def _normalize_update(body: TestSuiteUpdate) -> tuple[dict, list[str] | None]:
    data = body.model_dump(exclude_unset=True)
    repo_ids = data.pop("repository_ids", None) if "repository_ids" in data else None
    if "slug" in data and data["slug"]:
        data["slug"] = data["slug"].strip().lower()
    if "name" in data and data["name"]:
        data["name"] = data["name"].strip()
    if "description" in data:
        v = data["description"]
        data["description"] = (v or "").strip() or None
    if "external_ref" in data:
        v = data["external_ref"]
        data["external_ref"] = (v or "").strip() or None
    for key in ("git_url", "git_branch", "case_path", "trigger_webhook_url"):
        if key in data:
            v = data[key]
            data[key] = (v or "").strip() or None
    return data, repo_ids


@router.get("")
def list_test_suites(
    db: Session = Depends(get_db),
    q: str | None = Query(None, description="按标识或名称搜索"),
    enabled_only: bool = Query(False),
) -> dict:
    stmt = select(TestSuite).order_by(TestSuite.name.asc())
    if enabled_only:
        stmt = stmt.where(TestSuite.enabled.is_(True))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where((TestSuite.slug.ilike(like)) | (TestSuite.name.ilike(like)))
    rows = db.scalars(stmt).all()
    return {"items": [_to_out(r, db) for r in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_test_suite(body: TestSuiteCreate, db: Session = Depends(get_db)) -> dict:
    fields, repo_ids = _normalize_create(body)
    slug = fields["slug"]
    row = TestSuite(
        id=str(uuid.uuid4()),
        slug=slug,
        name=fields["name"],
        description=fields["description"],
        external_ref=fields["external_ref"],
        enabled=fields["enabled"],
        source_type=fields.get("source_type") or "manual",
        git_url=fields.get("git_url"),
        git_branch=fields.get("git_branch") or ("main" if fields.get("source_type") == "git" else None),
        case_path=fields.get("case_path"),
        framework=fields.get("framework"),
        git_reuse_repository_id=fields.get("git_reuse_repository_id"),
        git_auth_method=fields.get("git_auth_method") or "inherit",
        access_token=fields.get("access_token"),
        ssh_private_key=fields.get("ssh_private_key"),
        trigger_webhook_url=fields.get("trigger_webhook_url"),
        skip_ssl_verify=bool(fields.get("skip_ssl_verify")),
    )
    db.add(row)
    try:
        db.flush()
        bind_repositories(db, row, repo_ids)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="用例集标识已存在") from exc
    db.refresh(row)
    return _to_out(row, db)


@router.post("/branches")
def list_test_suite_branches(
    body: TestSuiteBranchesIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
) -> dict:
    bearer = bearer_token_from_header(authorization)
    suite = db.get(TestSuite, body.test_suite_id) if body.test_suite_id else None
    result = list_suite_source_branches(
        db,
        git_url=body.git_url,
        git_reuse_repository_id=body.git_reuse_repository_id,
        git_auth_method=body.git_auth_method,
        access_token=body.access_token,
        ssh_private_key=body.ssh_private_key,
        bearer_session_token=bearer,
        suite=suite,
        skip_ssl_verify=body.skip_ssl_verify,
    )
    return result


@router.post("/preview", response_model=TestSuitePreviewOut)
def preview_test_suite(
    body: TestSuitePreviewIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
) -> dict:
    """连通性 + 分支/目录校验 + 浅层拉取扫描用例（复用凭据链，5s 超时）。"""
    bearer = bearer_token_from_header(authorization)
    suite = db.get(TestSuite, body.test_suite_id) if body.test_suite_id else None
    clone_url = (body.clone_url or "").strip() or None
    linked = body.linked_repo_id
    if linked and not clone_url:
        repo = db.get(Repository, linked)
        if repo and (repo.clone_url or "").strip():
            clone_url = repo.clone_url.strip()
    return preview_suite_source(
        db,
        source_type=body.source_type,
        clone_url=clone_url,
        linked_repo_id=linked,
        credential_mode=body.credential_mode,
        access_token=body.access_token,
        ssh_private_key=body.ssh_private_key,
        verify_ssl=body.verify_ssl,
        branch=body.branch,
        scan_path=body.scan_path,
        framework=body.framework,
        bearer_session_token=bearer,
        suite=suite,
    )


@router.post("/probe")
def probe_test_suite(
    body: TestSuiteProbeIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
) -> dict:
    bearer = bearer_token_from_header(authorization)
    result = probe_suite_source(
        db,
        git_url=body.git_url,
        git_reuse_repository_id=body.git_reuse_repository_id,
        git_branch=body.git_branch,
        case_path=body.case_path,
        framework=body.framework,
        git_auth_method=body.git_auth_method,
        access_token=body.access_token,
        ssh_private_key=body.ssh_private_key,
        bearer_session_token=bearer,
        skip_ssl_verify=body.skip_ssl_verify,
    )
    return result.as_dict()


@router.get("/{suite_id}")
def get_test_suite(suite_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.get(TestSuite, suite_id)
    if not row:
        raise HTTPException(status_code=404, detail="用例集不存在")
    return _to_out(row, db)


@router.patch("/{suite_id}")
def update_test_suite(suite_id: str, body: TestSuiteUpdate, db: Session = Depends(get_db)) -> dict:
    row = db.get(TestSuite, suite_id)
    if not row:
        raise HTTPException(status_code=404, detail="用例集不存在")
    old_slug = row.slug
    data, repo_ids = _normalize_update(body)

    new_slug = data.get("slug", old_slug)
    if new_slug != old_slug:
        in_use = _repo_count_by_slug(db, old_slug)
        if in_use:
            repos = db.scalars(select(Repository).where(Repository.test_suite_id == old_slug)).all()
            for repo in repos:
                repo.test_suite_id = new_slug

    scalar_keys = {
        "slug",
        "name",
        "description",
        "external_ref",
        "enabled",
        "source_type",
        "framework",
        "skip_ssl_verify",
    }
    for key in scalar_keys:
        if key in data:
            setattr(row, key, data[key])
    _apply_source_fields(row, data)
    if "git_auth_method" in data and data["git_auth_method"]:
        row.git_auth_method = data["git_auth_method"]
    for secret_key in ("access_token", "ssh_private_key"):
        if secret_key in data:
            value = data[secret_key]
            if not value:
                continue
            setattr(row, secret_key, value)

    try:
        db.flush()
        if repo_ids is not None:
            bind_repositories(db, row, repo_ids)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="用例集标识已存在") from exc
    db.refresh(row)
    return _to_out(row, db)


@router.post("/{suite_id}/sync")
def sync_suite(
    suite_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
) -> dict:
    row = db.get(TestSuite, suite_id)
    if not row:
        raise HTTPException(status_code=404, detail="用例集不存在")
    bearer = bearer_token_from_header(authorization)
    result = sync_test_suite(db, row, bearer_session_token=bearer)
    db.commit()
    db.refresh(row)
    out = _to_out(row, db)
    out.update(result.as_dict())
    return out


@router.delete("/{suite_id}")
def delete_test_suite(suite_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.get(TestSuite, suite_id)
    if not row:
        raise HTTPException(status_code=404, detail="用例集不存在")
    in_use = _repo_count_by_slug(db, row.slug)
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=f"仍有 {in_use} 个仓库关联此用例集，请先解除关联或停用",
        )
    db.delete(row)
    db.commit()
    return {"ok": True}