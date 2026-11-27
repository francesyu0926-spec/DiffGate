from app.adapters.registry import list_repo_type_options, normalize_repo_type, repo_type_index_supported
from app.graph.call_graph import CallGraph
from app.adapters.protocol import RepoGraphIR
from app.parsers.python_ast import SymbolDef


def test_normalize_repo_type():
    assert normalize_repo_type("backend") == "backend_python"
    assert normalize_repo_type(None) == "backend_python"


def test_repo_type_meta():
    items = list_repo_type_options()
    ids = {i["id"] for i in items}
    assert "backend_python" in ids
    assert "backend_go" in ids
    assert not repo_type_index_supported("backend_go")


def test_ir_from_python():
    sym = SymbolDef(
        qualified_name="app.main.hello",
        file_path="app/main.py",
        kind="function",
        start_line=1,
        end_line=3,
        is_api_handler=True,
        http_method="GET",
        route_path="/hello",
    )
    g = CallGraph()
    g.add_symbols([sym])
    ir = RepoGraphIR.from_python_index(
        repo_id="r1",
        repo_full_name="acme/api",
        symbols=[sym],
        graph=g,
        uid_fn=lambda rid, f, q: f"{rid}:{f}:{q}",
    )
    assert ir.endpoints[0].path == "/hello"