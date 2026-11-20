import logging

import httpx

from app.config import get_settings
from app.engine.reverse_trace import ImpactReport

logger = logging.getLogger(__name__)


def notify_dispatch_center(
    job_id: str,
    repo: str,
    ref: str,
    report: ImpactReport,
    *,
    test_suite_id: str | None = None,
) -> None:
    """第四步：将受影响接口清单推送至精准回归调度中心。"""
    settings = get_settings()
    if not settings.dispatch_center_url:
        return

    payload = {
        "job_id": job_id,
        "repo": repo,
        "ref": ref,
        "interfaces": [
            {"method": api["method"], "path": api["path"]} for api in report.affected_apis
        ],
        "call_paths": report.call_paths,
        "suspects": [s.qualified_name for s in report.suspect_functions],
        "stats": report.to_dict()["stats"],
        "test_suite_id": test_suite_id,
        "gate_report_url": f"/api/v1/jobs/{job_id}/gate-report",
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(settings.dispatch_center_url, json=payload)
            resp.raise_for_status()
    except Exception:
        logger.exception("dispatch center notify failed for job %s", job_id)