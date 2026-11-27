from pathlib import Path

from app.parsers.fullstack_normalize import clean_repo_rel_path, normalize_fullstack_impact
from app.parsers.fullstack_sanitize import sanitize_fullstack_payload, tree_sitter_scan_shape


def test_clean_repo_rel_path():
    raw = (
        "data/worktrees/0aaf8810-7457-4648-92a4-4b8a2b502f58/"
        "francesyu0926-spec_QuantLens/frontend/src/App.tsx"
    )
    assert clean_repo_rel_path(raw) == "frontend/src/App.tsx"


def test_normalize_filters_dash_and_aggregates_lines():
    norm = normalize_fullstack_impact(
        [{"route": "—", "component": "frontend/src/Foo.tsx"}],
        [
            {
                "file": "data/worktrees/uuid/frontend/src/Foo.tsx",
                "method": "GET",
                "endpoint": "/radar",
                "line": 10,
            },
            {
                "file": "data/worktrees/uuid/frontend/src/Foo.tsx",
                "method": "GET",
                "endpoint": "/radar",
                "line": 12,
            },
            {"file": "frontend/src/Bar.tsx", "method": "-", "endpoint": "-", "line": 1},
        ],
    )
    assert norm["components"][0]["file"] == "frontend/src/Foo.tsx"
    assert len(norm["matched_api_calls"]) == 1
    assert norm["matched_api_calls"][0]["lines"] == [10, 12]
    assert norm["unresolved_count"] == 1


def test_normalize_with_worktree_dir_repo_root():
    wt = Path("D:/sandbox/data/worktrees/uuid/francesyu0926-spec_QuantLens")
    abs_file = wt / "frontend/src/App.tsx"
    norm = normalize_fullstack_impact(
        [{"route": "—", "component": str(abs_file)}],
        [{"file": str(abs_file), "method": "GET", "endpoint": "/x", "line": 3}],
        repo_root=str(wt),
    )
    assert norm["components"][0]["file"] == "frontend/src/App.tsx"


def test_sanitize_mirrors_legacy_fields():
    raw = {
        "frontend_api_calls": [
            {
                "file": "data/worktrees/x/frontend/src/Foo.tsx",
                "line": 10,
                "backend_path": "/radar",
                "backend_method": "GET",
            },
        ],
        "affected_routes": [{"route_path": "—", "component_file": "data/worktrees/x/frontend/src/Foo.tsx"}],
    }
    out = sanitize_fullstack_payload(raw)
    assert out["matched_api_calls"][0]["file"] == "frontend/src/Foo.tsx"
    assert out["frontend_api_calls_aggregated"][0]["lines"] == [10]
    assert out["frontend_api_calls_aggregated"][0]["backend_paths"] == ["/radar"]