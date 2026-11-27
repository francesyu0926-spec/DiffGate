from types import SimpleNamespace

from app.services.im_notify import (
    build_im_payload,
    build_test_notify_payload,
    regression_link,
    webhook_vendor_from_url,
)


def test_regression_link_contains_job_id():
    job = SimpleNamespace(id="abc-123", repo_full_name="acme/x", head_sha="deadbeef")
    gr = {
        "gate": "BLOCK",
        "block_reason": "incremental_coverage_low",
        "block_reason_label": "增量覆盖率不足",
        "incremental_coverage_pct": 12.0,
        "coverage_threshold": 80,
    }
    url = regression_link(job.id, action="override")
    assert "regression" in url
    assert "job_id" in url
    assert "abc-123" in url
    payload = build_im_payload(
        job,
        gr,
        vendor="feishu",
        regression_url=regression_link(job.id),
        override_url=url,
    )
    assert payload["msg_type"] == "interactive"