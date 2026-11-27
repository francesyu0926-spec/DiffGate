from app.services.git_secrets import redact_url_credentials
from app.services.gitlab_private import encode_gitlab_project_path, webhook_core_fingerprint


def test_encode_nested_gitlab_path():
    enc = encode_gitlab_project_path("tech/payment/core/api-tests")
    assert enc == "tech%2Fpayment%2Fcore%2Fapi-tests"


def test_webhook_fingerprint_ignores_port():
    a = "http://192.168.1.10:8080/group/proj.git"
    b = "https://192.168.1.10/group/proj"
    assert webhook_core_fingerprint(a) == webhook_core_fingerprint(b)


def test_redact_token_in_clone_url():
    raw = "https://oauth2:supersecret@gitlab.corp/qa/tests.git"
    assert "supersecret" not in redact_url_credentials(raw)
    assert "***@" in redact_url_credentials(raw)