from pathlib import Path

from app.graph.call_graph import CallGraph
from app.parsers.python_ast import scan_python_repo


FIXTURE = Path(__file__).parent / "fixtures" / "sample_app"


def test_reverse_reach_api_from_util():
    symbols = scan_python_repo(FIXTURE)
    graph = CallGraph()
    graph.add_symbols(symbols)

    changed = {"app.utils.formatter.format_name"}
    apis = graph.affected_apis(changed)

    assert len(apis) == 1
    assert apis[0]["path"] == "/users/{user_id}"
    assert apis[0]["method"] == "GET"