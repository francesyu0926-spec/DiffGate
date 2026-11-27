from app.graph.call_graph import CallGraph
from app.graph.neo4j_contracts import Neo4jGlobalGraph, resolve_symbol_uid, symbol_uid
from app.parsers.python_ast import SymbolDef


def _sym(name: str, file: str = "app/x.py") -> SymbolDef:
    return SymbolDef(
        qualified_name=name,
        file_path=file,
        start_line=1,
        end_line=2,
        kind="function",
        calls=[],
    )


def test_resolve_symbol_uid_known_and_external():
    by_name = {"pkg.foo": _sym("pkg.foo")}
    rid = "repo-1"
    assert resolve_symbol_uid(rid, "pkg.foo", by_name) == symbol_uid(rid, "app/x.py", "pkg.foo")
    assert resolve_symbol_uid(rid, "other.bar", by_name) == symbol_uid(rid, "__external__", "other.bar")


def test_merge_reverse_trace_dedupes():
    gg = Neo4jGlobalGraph(store=object())
    rows = gg._merge_reverse_trace_rows(
        [
            {"api_uid": "a1", "changed_uid": "c1", "trace_kind": "local", "call_depth": 2},
            {"api_uid": "a1", "changed_uid": "c1", "trace_kind": "local", "call_depth": 2},
        ],
        [{"api_uid": "a2", "changed_uid": "c1", "trace_kind": "cross_repo", "call_depth": 3}],
    )
    assert len(rows) == 2
    assert rows[0]["call_depth"] == 2