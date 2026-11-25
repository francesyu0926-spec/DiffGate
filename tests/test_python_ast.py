import ast
import textwrap
from pathlib import Path

from app.parsers.python_ast import parse_python_file, scan_python_repo

FIXTURE = Path(__file__).parent / "fixtures" / "sample_app"


def _parse_snippet(code: str, module: str = "app.sample", rel: str = "app/sample.py"):
    tree = ast.parse(textwrap.dedent(code))
    from app.parsers.python_ast import SymbolVisitor

    visitor = SymbolVisitor(module, rel)
    visitor.visit(tree)
    return visitor.symbols


def test_imported_function_call_resolved():
    code = """
    from app.utils.formatter import format_name

    def handler(x: int):
        return format_name(str(x))
    """
    syms = _parse_snippet(code)
    handler = next(s for s in syms if s.qualified_name.endswith(".handler"))
    assert "app.utils.formatter.format_name" in handler.calls
    assert "format_name" in handler.calls


def test_self_method_call_resolved():
    code = """
    class Worker:
        def run(self):
            return self.work()

        def work(self):
            return 1
    """
    syms = _parse_snippet(code)
    run = next(s for s in syms if s.qualified_name.endswith(".Worker.run"))
    assert "app.sample.Worker.work" in run.calls
    assert "self.work" in run.calls or "work" in run.calls


def test_instance_attribute_call_resolved():
    code = """
    class ProfileService:
        def load_one(self):
            return 1

    collector = ProfileService()

    async def load():
        await collector.load_one()
    """
    syms = _parse_snippet(code)
    load = next(s for s in syms if s.qualified_name.endswith(".load"))
    assert any("ProfileService.load_one" in c or c.endswith(".load_one") for c in load.calls)


def test_async_await_call_extracted():
    code = """
    from app.quotes import fetch_quotes

    async def quotes_api(symbols):
        return await fetch_quotes(symbols)
    """
    syms = _parse_snippet(code)
    api = next(s for s in syms if s.qualified_name.endswith(".quotes_api"))
    assert "app.quotes.fetch_quotes" in api.calls


def test_scan_quant_lens_collector_chain():
    repo = Path(__file__).resolve().parents[1] / "data/repos/francesyu0926-spec_QuantLens"
    if not repo.is_dir():
        return
    symbols = scan_python_repo(repo, "backend")
    klines = next((s for s in symbols if s.qualified_name.endswith(".klines")), None)
    assert klines is not None
    joined = " ".join(klines.calls)
    assert "ensure_history" in joined
    assert (
        "MarketCollector.ensure_history" in joined
        or "collector.ensure_history" in joined
        or ".ensure_history" in joined
    )