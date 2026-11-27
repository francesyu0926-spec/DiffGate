"""测试环境探针控制：落盘 flush、combine、轮次 reset（配合长驻 FastAPI / uvicorn workers）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.coverage_lifecycle import coverage_combine, coverage_reset

router = APIRouter(prefix="/probe", tags=["probe"])


class ProbeDataDirIn(BaseModel):
    coverage_data_dir: str = Field(..., min_length=1, max_length=512)
    combine: bool = True
    reset: bool = False


@router.post("/reset")
def probe_reset(body: ProbeDataDirIn) -> dict:
    data_dir = Path(body.coverage_data_dir)
    n = coverage_reset(data_dir)
    return {"ok": True, "removed_files": n, "coverage_data_dir": str(data_dir)}


@router.post("/flush")
def probe_flush(body: ProbeDataDirIn) -> dict:
    """
    合并多 worker 分片并落盘；CI 应在每条用例后 save、批次 gate-report 前调用本接口。
    """
    data_dir = Path(body.coverage_data_dir)
    if body.reset:
        coverage_reset(data_dir)
    if body.combine:
        try:
            coverage_combine(data_dir)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"coverage combine failed: {exc}") from exc
    files = [p.name for p in sorted(data_dir.glob(".coverage*")) if data_dir.is_dir()]
    return {"ok": True, "coverage_data_dir": str(data_dir), "files": files}