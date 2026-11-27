"""用例索引落库（增量统计 + 全量写入）。"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import IndexedCaseApiBinding, IndexedTestCase
from app.services.testcase_yaml_index import ParsedCase


@dataclass
class SyncIndexStats:
    added: int = 0
    updated: int = 0
    removed: int = 0
    api_count: int = 0
    case_count: int = 0

    def summary_message(self) -> str:
        return (
            f"同步完成：新增 {self.added} 条，更新 {self.updated} 条，"
            f"移除 {self.removed} 条，共覆盖 {self.api_count} 个 API"
        )


def _case_content_hash(pc: ParsedCase) -> str:
    bindings = sorted(
        (b.http_method, b.contract_key, b.normalized_route) for b in pc.bindings
    )
    payload = {
        "title": pc.title,
        "run_selector": pc.run_selector,
        "file_path": pc.file_path,
        "bindings": bindings,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _snapshot_suite(db: Session, suite_id: str) -> tuple[set[str], dict[str, str], int]:
    rows = db.scalars(select(IndexedTestCase).where(IndexedTestCase.suite_id == suite_id)).all()
    uids = {r.case_uid for r in rows}
    hashes: dict[str, str] = {}
    for row in rows:
        binds = db.scalars(
            select(IndexedCaseApiBinding).where(IndexedCaseApiBinding.case_id == row.id)
        ).all()
        binds_payload = sorted((b.http_method, b.contract_key, b.normalized_route) for b in binds)
        payload = {
            "title": row.title,
            "run_selector": row.run_selector,
            "file_path": row.file_path,
            "bindings": binds_payload,
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        hashes[row.case_uid] = hashlib.sha256(raw.encode()).hexdigest()
    api_n = (
        db.scalar(
            select(func.count(func.distinct(IndexedCaseApiBinding.contract_key)))
            .select_from(IndexedCaseApiBinding)
            .join(IndexedTestCase, IndexedTestCase.id == IndexedCaseApiBinding.case_id)
            .where(IndexedTestCase.suite_id == suite_id)
        )
        or 0
    )
    return uids, hashes, api_n


def clear_suite_index(db: Session, suite_id: str) -> None:
    case_ids = list(db.scalars(select(IndexedTestCase.id).where(IndexedTestCase.suite_id == suite_id)).all())
    if case_ids:
        db.execute(delete(IndexedCaseApiBinding).where(IndexedCaseApiBinding.case_id.in_(case_ids)))
    db.execute(delete(IndexedTestCase).where(IndexedTestCase.suite_id == suite_id))


def _write_cases(db: Session, suite_id: str, cases: list[ParsedCase]) -> int:
    api_keys: set[str] = set()
    for pc in cases:
        case_id = str(uuid.uuid4())
        db.add(
            IndexedTestCase(
                id=case_id,
                suite_id=suite_id,
                case_uid=pc.case_uid,
                title=pc.title,
                run_selector=pc.run_selector,
                source_framework=pc.source_framework,
                file_path=pc.file_path,
                tags=None,
            )
        )
        for b in pc.bindings:
            api_keys.add(b.contract_key)
            db.add(
                IndexedCaseApiBinding(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    http_method=b.http_method,
                    raw_route=b.raw_route,
                    normalized_route=b.normalized_route,
                    contract_key=b.contract_key,
                )
            )
    return len(api_keys)


def merge_suite_index(db: Session, suite_id: str, cases: list[ParsedCase]) -> SyncIndexStats:
    old_uids, old_hashes, _old_api = _snapshot_suite(db, suite_id)
    new_uids = {c.case_uid for c in cases}
    new_hashes = {c.case_uid: _case_content_hash(c) for c in cases}

    added = len(new_uids - old_uids)
    removed = len(old_uids - new_uids)
    updated = 0
    for uid in new_uids & old_uids:
        if new_hashes.get(uid) != old_hashes.get(uid):
            updated += 1

    clear_suite_index(db, suite_id)
    api_count = _write_cases(db, suite_id, cases)

    return SyncIndexStats(
        added=added,
        updated=updated,
        removed=removed,
        api_count=api_count,
        case_count=len(cases),
    )


def replace_suite_index(db: Session, suite_id: str, cases: list[ParsedCase]) -> tuple[int, int]:
    """兼容旧调用：无增量统计。"""
    clear_suite_index(db, suite_id)
    api_n = _write_cases(db, suite_id, cases)
    return api_n, len(cases)