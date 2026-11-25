"""本地测试环境：精准回归调度中心回调（接收第四步推送并执行 coverage 探针）。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from app.services.coverage_probe import run_coverage_probe_for_job_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dispatch", tags=["dispatch"])


class DispatchRegressionIn(BaseModel):
    job_id: str = Field(..., min_length=1)
    repo: str | None = None
    ref: str | None = None
    interfaces: list[dict[str, Any]] = Field(default_factory=list)
    gate_report_url: str | None = None


def _run_probe_task(job_id: str) -> None:
    try:
        result = run_coverage_probe_for_job_id(job_id)
        if result:
            logger.info(
                "coverage probe finished job=%s pct=%.1f tests_passed=%s",
                job_id,
                result.incremental_coverage_pct,
                result.tests_passed,
            )
    except Exception:
        logger.exception("coverage probe failed for job %s", job_id)


@router.post("/regression")
def accept_regression_dispatch(
    body: DispatchRegressionIn,
    background_tasks: BackgroundTasks,
) -> dict[str, bool | str]:
    background_tasks.add_task(_run_probe_task, body.job_id)
    return {"ok": True, "accepted": body.job_id}