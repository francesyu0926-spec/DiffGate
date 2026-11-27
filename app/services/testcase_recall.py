"""精准回归：受影响 API → 索引用例召回、缺口检测与执行指令。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AnalysisJob, IndexedCaseApiBinding, IndexedTestCase, Repository, TestSuite
from app.services.testcase_fingerprint import (
    contract_key_to_fingerprint,
    contract_keys_from_affected_apis,
    fingerprints_from_affected_apis,
)


def _resolve_suite_for_job(db: Session, job: AnalysisJob) -> tuple[TestSuite | None, Repository | None]:
    repo = db.scalar(select(Repository).where(Repository.full_name == job.repo_full_name))
    slug = (repo.test_suite_id or "").strip() if repo else ""
    if not slug:
        return None, repo
    suite = db.scalar(select(TestSuite).where(TestSuite.slug == slug))
    return suite, repo


def _build_execution_command(hit_cases: list[dict], framework: str | None) -> dict:
    fw = (framework or "yaml").lower()
    selectors = [c["run_selector"] for c in hit_cases if c.get("run_selector")]
    case_uids = [c["case_uid"] for c in hit_cases]
    unique_selectors = list(dict.fromkeys(selectors))

    out: dict = {
        "framework": fw,
        "case_uids": case_uids,
        "selectors": unique_selectors,
        "pytest_command": None,
        "yaml_paths": None,
        "apifox_case_ids": None,
        "shell_one_liner": None,
    }

    if fw == "pytest":
        parts = " ".join(unique_selectors)
        out["pytest_command"] = f"pytest {parts}" if parts else "pytest"
        out["shell_one_liner"] = out["pytest_command"]
    elif fw in ("yaml", "httprunner"):
        out["yaml_paths"] = unique_selectors
        out["shell_one_liner"] = "\n".join(unique_selectors)
    elif fw == "apifox":
        out["apifox_case_ids"] = case_uids
        out["shell_one_liner"] = ", ".join(case_uids)
    else:
        out["shell_one_liner"] = "\n".join(unique_selectors)

    return out


def build_precision_recall(db: Session, job: AnalysisJob) -> dict:
    suite, repo = _resolve_suite_for_job(db, job)
    affected = job.affected_apis or {}
    contract_keys = contract_keys_from_affected_apis(affected)
    fingerprints = fingerprints_from_affected_apis(affected)

    total_indexed = 0
    if suite:
        total_indexed = (
            db.scalar(select(func.count()).select_from(IndexedTestCase).where(IndexedTestCase.suite_id == suite.id))
            or 0
        )

    if not suite or not contract_keys:
        return {
            "bound": bool(suite),
            "test_suite_slug": suite.slug if suite else None,
            "test_suite_name": suite.name if suite else None,
            "total_indexed_cases": total_indexed,
            "affected_fingerprints": fingerprints,
            "affected_contract_keys": contract_keys,
            "hit_cases": [],
            "hit_case_count": 0,
            "case_reduction_pct": None,
            "gaps": [
                {
                    "fingerprint": fp,
                    "contract_key": ck,
                    "missing": True,
                    "label": "缺失测试用例",
                }
                for fp, ck in zip(fingerprints, contract_keys)
            ],
            "execution": _build_execution_command([], suite.framework if suite else None),
            "webhook_payload": {
                "job_id": job.id,
                "api_list": fingerprints,
                "case_uids": [],
                "selectors": [],
            },
        }

    stmt = (
        select(IndexedTestCase, IndexedCaseApiBinding)
        .join(IndexedCaseApiBinding, IndexedCaseApiBinding.case_id == IndexedTestCase.id)
        .where(
            IndexedTestCase.suite_id == suite.id,
            IndexedCaseApiBinding.contract_key.in_(contract_keys),
        )
    )
    rows = db.execute(stmt).all()

    cases_map: dict[str, dict] = {}
    for case_row, bind in rows:
        cid = case_row.id
        if cid not in cases_map:
            cases_map[cid] = {
                "case_uid": case_row.case_uid,
                "title": case_row.title,
                "run_selector": case_row.run_selector,
                "file_path": case_row.file_path,
                "source_framework": case_row.source_framework,
                "matched_fingerprints": [],
                "matched_contract_keys": [],
            }
        fp = contract_key_to_fingerprint(bind.contract_key)
        bucket = cases_map[cid]
        if fp not in bucket["matched_fingerprints"]:
            bucket["matched_fingerprints"].append(fp)
        if bind.contract_key not in bucket["matched_contract_keys"]:
            bucket["matched_contract_keys"].append(bind.contract_key)

    hit_cases = list(cases_map.values())
    hit_count = len(hit_cases)
    matched_keys = {k for c in hit_cases for k in c["matched_contract_keys"]}

    gaps = []
    for fp, ck in zip(fingerprints, contract_keys):
        if ck not in matched_keys:
            gaps.append(
                {
                    "fingerprint": fp,
                    "contract_key": ck,
                    "missing": True,
                    "label": "缺失测试用例",
                }
            )

    reduction = None
    if total_indexed > 0 and hit_count > 0:
        reduction = round((1 - hit_count / total_indexed) * 100, 1)
        reduction = min(99.9, max(0.0, reduction))

    execution = _build_execution_command(hit_cases, suite.framework)
    webhook_url = (suite.trigger_webhook_url or "").strip() if suite.source_type == "webhook" else ""

    return {
        "bound": True,
        "test_suite_slug": suite.slug,
        "test_suite_name": suite.name,
        "repository": job.repo_full_name,
        "repo_test_suite_id": repo.test_suite_id if repo else None,
        "total_indexed_cases": total_indexed,
        "affected_fingerprints": fingerprints,
        "affected_contract_keys": contract_keys,
        "hit_cases": hit_cases,
        "hit_case_count": hit_count,
        "case_reduction_pct": reduction,
        "gaps": gaps,
        "execution": execution,
        "webhook_payload": {
            "job_id": job.id,
            "repo": job.repo_full_name,
            "api_list": fingerprints,
            "case_uids": execution["case_uids"],
            "selectors": execution["selectors"],
        },
        "webhook_dispatch_url": webhook_url or None,
    }