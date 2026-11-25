from app.api.regression import _build_case_rows


def test_block_for_low_coverage_does_not_fake_first_fail():
    apis = [{"method": "GET", "path": "/catalog/search"}]
    gr = {"gate": "BLOCK", "block_reason": "incremental_coverage_low"}
    cases = _build_case_rows(apis, "BLOCK", gr)
    assert cases[0]["status"] == "PASS"
    assert cases[0]["response_preview"]
    assert "assertion failed" not in cases[0]["response_preview"]


def test_smoke_fail_marks_case_and_shows_body():
    apis = [{"method": "GET", "path": "/catalog/search"}]
    gr = {
        "api_smoke_results": [
            {
                "method": "GET",
                "path": "/catalog/search",
                "status_code": 404,
                "body": '{"detail":"Not Found"}',
            }
        ]
    }
    cases = _build_case_rows(apis, "PASS", gr)
    assert cases[0]["status"] == "FAIL"
    assert "Not Found" in cases[0]["response_preview"]