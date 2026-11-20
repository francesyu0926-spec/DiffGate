from app.graph.call_graph import CallGraph
from app.parsers.python_ast import SymbolDef


def _sym(qname: str, calls: list[str], **kwargs) -> SymbolDef:
    short = qname.split(".")[-1]
    return SymbolDef(
        qualified_name=qname,
        file_path=f"{qname.replace('.', '/')}.py",
        kind="function",
        start_line=1,
        end_line=10,
        calls=calls,
        **kwargs,
    )


def test_bfs_survives_cycle_and_finds_api():
    graph = CallGraph()
    graph.add_symbols(
        [
            _sym("app.util.calc_price", [],),
            _sym(
                "app.service.create_order_service",
                ["calc_price"],
            ),
            _sym(
                "app.api.create_order",
                ["create_order_service"],
                is_api_handler=True,
                http_method="post",
                route_path="/api/v1/order",
            ),
            _sym("app.service.update_cart_service", ["calc_price", "create_order_service"]),
        ]
    )
    # artificial mutual reference on short names
    graph.reverse["create_order_service"].add("app.service.update_cart_service")
    graph.reverse["update_cart_service"].add("app.service.create_order_service")

    traces = graph.reverse_bfs_traces({"app.util.calc_price"})
    assert len(traces) >= 1
    order = next(t for t in traces if t["path"] == "/api/v1/order")
    assert "calc_price" in order["chain_labels"][0] or order["chain_labels"][0] == "calc_price"
    assert order["method"] == "POST"