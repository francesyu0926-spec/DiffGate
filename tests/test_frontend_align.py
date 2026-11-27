from pathlib import Path

from app.parsers.frontend_contract import (
    ApiPathAlign,
    normalize_frontend_api_path,
    normalize_plus_concatenated_path,
    read_env_api_base,
)


def test_strip_query_and_concat():
    assert normalize_frontend_api_path("/jobs?status=failed", align=ApiPathAlign(prefix="/api/v1")) == "/api/v1/jobs"
    assert normalize_plus_concatenated_path("'/jobs/' + id + '/graph'") == "/jobs/*/graph"


def test_strip_gateway_prefix():
    align = ApiPathAlign(prefix="", strip_prefix="/api/billing")
    assert normalize_frontend_api_path("/api/billing/charge", align=align) == "/charge"


def test_read_env_base(tmp_path: Path):
    (tmp_path / ".env.production").write_text('VITE_API_BASE="/api/v1"\n', encoding="utf-8")
    assert read_env_api_base(tmp_path) == "/api/v1"