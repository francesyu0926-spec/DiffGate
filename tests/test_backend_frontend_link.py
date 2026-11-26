from pathlib import Path

from app.parsers.frontend_trace import build_fullstack_impact


def test_backend_api_links_quant_lens_frontend(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1] / "data/repos/francesyu0926-spec_QuantLens"
    if not repo.is_dir():
        return
    backend = [
        {"method": "GET", "path": "/klines", "handler": "klines"},
        {"method": "GET", "path": "/radar", "handler": "radar"},
    ]
    out = build_fullstack_impact(
        repo,
        set(),
        scan_roots=("frontend",),
        backend_apis=backend,
    )
    calls = out.get("frontend_api_calls") or []
    assert len(calls) >= 2
    files = {c["file"] for c in calls}
    assert any("marketApi" in f or "AiDiagnose" in f or "Radar" in f for f in files)