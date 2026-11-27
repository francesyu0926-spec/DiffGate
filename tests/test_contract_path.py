from app.parsers.http_client_scan import http_client_confidence, normalize_contract_path


def test_normalize_fastapi_params():
    assert normalize_contract_path("/users/{user_id}") == "/users/*"
    assert normalize_contract_path("/users/123") == "/users/*"


def test_dynamic_confidence():
    assert http_client_confidence('/users/{uid}') == 0.6
    assert http_client_confidence('/api/v1/orders') == 0.85