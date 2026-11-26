from pathlib import Path

from app.parsers.http_client_scan import match_consumers, scan_repo_http_clients


def test_python_client_match(tmp_path: Path):
    svc = tmp_path / "app" / "clients"
    svc.mkdir(parents=True)
    (svc / "gateway.py").write_text(
        'import httpx\n\ndef pull():\n    return httpx.get("http://order-svc/api/v1/orders")\n',
        encoding="utf-8",
    )
    hits = scan_repo_http_clients(tmp_path, "consumer/order-ui")
    matched = match_consumers(hits, ["/api/v1/orders"])
    assert len(matched) >= 1
    assert matched[0]["matched_api"] == "/api/v1/orders"