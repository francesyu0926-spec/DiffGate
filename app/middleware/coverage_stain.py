"""探针染色：仅当请求携带 X-DiffGate-Job-Id 时写入 job 级 coverage 上下文。"""

from __future__ import annotations

import contextvars
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

JOB_HEADER = "X-DiffGate-Job-Id"

active_job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "diffgate_active_job_id", default=None
)


def get_active_job_id() -> str | None:
    return active_job_id.get()


class CoverageStainMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        job_id = request.headers.get(JOB_HEADER)
        token = active_job_id.set(job_id.strip() if job_id else None)
        try:
            return await call_next(request)
        finally:
            active_job_id.reset(token)


# 被测应用可在入口调用：from app.middleware.coverage_stain import patch_coverage_for_staining
# 探针模式默认通过请求头染色（见 coverage_probe.TestClient headers）。