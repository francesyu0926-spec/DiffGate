"""精准回归探针 CLI：对指定 AnalysisJob 执行 coverage 并回传 gate-report。

用法（项目根目录）:
  python scripts/coverage.py --job-id <uuid>
  python scripts/coverage.py --job-id <uuid> --api-base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
# 避免 scripts/coverage.py 遮蔽第三方 coverage 包
sys.path = [str(ROOT)] + [
    p for p in sys.path if Path(p).resolve() not in (ROOT.resolve(), SCRIPT_DIR.resolve())
]

from app.config import get_settings  # noqa: E402
from app.services.coverage_probe import (  # noqa: E402
    run_coverage_probe_for_job_id,
    submit_gate_report_http,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="DiffGate incremental coverage probe")
    parser.add_argument("--job-id", required=True, help="AnalysisJob id")
    parser.add_argument("--api-base", default=None, help="DiffGate API 根地址")
    parser.add_argument(
        "--http",
        action="store_true",
        help="写库后再 POST gate-report（默认仅写库）",
    )
    parser.add_argument(
        "--coverage-data-dir",
        default=None,
        help="CI 已落盘的 .coverage 目录（将 combine 后解析，不重复冒烟）",
    )
    parser.add_argument(
        "--reset-coverage",
        action="store_true",
        help="探针前清空 coverage 数据目录",
    )
    args = parser.parse_args()

    if args.coverage_data_dir:
        import os

        os.environ["DIFFGATE_COVERAGE_DATA_DIR"] = args.coverage_data_dir
    if args.reset_coverage:
        import os

        os.environ["DIFFGATE_COVERAGE_RESET"] = "1"

    settings = get_settings()
    result = run_coverage_probe_for_job_id(args.job_id)
    if result is None:
        print(f"job not found: {args.job_id}", file=sys.stderr)
        return 1

    gate_payload: dict | None = None
    if args.http:
        gate_payload = submit_gate_report_http(
            args.job_id,
            result,
            api_base=args.api_base or settings.api_public_base_url,
        )

    print(
        json.dumps(
            {
                "job_id": args.job_id,
                "incremental_coverage_pct": result.incremental_coverage_pct,
                "tests_passed": result.tests_passed,
                "covered_changed_lines": result.covered_changed_lines,
                "changed_lines": result.changed_lines,
                "error": result.error,
                "gate_report": gate_payload,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())