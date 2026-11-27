"""coverage.py 探针数据生命周期：落盘 flush、多进程 combine、轮次 reset。"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def coverage_data_files(data_dir: Path) -> list[Path]:
    data_dir = data_dir.resolve()
    if not data_dir.is_dir():
        return []
    return sorted(data_dir.glob(".coverage*"))


def coverage_reset(data_dir: Path) -> int:
    """新一轮精准回归前清空上一轮脏数据。"""
    removed = 0
    for p in coverage_data_files(data_dir):
        try:
            p.unlink()
            removed += 1
        except OSError:
            logger.warning("coverage reset skip %s", p)
    return removed


def coverage_combine(data_dir: Path, *, data_suffix: bool = True) -> None:
    """合并 uvicorn 多 worker 产生的 .coverage.<pid> 分片。"""
    import coverage

    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    cov = coverage.Coverage(data_file=str(data_dir / ".coverage"), data_suffix=data_suffix)
    cov.combine()
    cov.save()
    logger.info("coverage combine saved under %s", data_dir)


def coverage_flush_in_memory(cov) -> None:
    """长驻进程内将内存命中写入 .coverage（gate-report 前必调）。"""
    cov.save()


def load_coverage_from_dir(data_dir: Path, *, source: str | None = None):
    """从已 combine 的目录加载 Coverage 实例。"""
    import coverage

    data_dir = data_dir.resolve()
    data_file = data_dir / ".coverage"
    if not data_file.is_file():
        coverage_combine(data_dir)
    cov = coverage.Coverage(data_file=str(data_file))
    cov.load()
    return cov.get_data()