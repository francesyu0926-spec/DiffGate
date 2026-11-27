from app.graph.neo4j_contracts import contract_key_http
from app.services.testcase_fingerprint import (
    contract_key_to_fingerprint,
    contract_keys_from_affected_apis,
    fingerprint_to_contract_key,
)


def test_fingerprint_roundtrip():
    ck = contract_key_http("POST", "/api/v1/orders/{id}")
    fp = contract_key_to_fingerprint(ck)
    assert fp == "POST:/api/v1/orders/*"
    assert fingerprint_to_contract_key(fp) == ck


def test_affected_apis_keys():
    keys = contract_keys_from_affected_apis(
        {"apis": [{"method": "GET", "path": "/api/v1/orders"}]}
    )
    assert keys == [contract_key_http("GET", "/api/v1/orders")]