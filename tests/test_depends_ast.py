import textwrap

from app.parsers.python_ast import SymbolVisitor


def test_fastapi_depends_edge():
    code = textwrap.dedent(
        """
        from fastapi import Depends

        def get_db():
            yield 1

        def handler(db=Depends(get_db)):
            return db
        """
    )
    import ast

    tree = ast.parse(code)
    visitor = SymbolVisitor("app.routes", "app/routes.py")
    visitor.visit(tree)
    handler = next(s for s in visitor.symbols if s.qualified_name.endswith(".handler"))
    assert any("get_db" in c for c in handler.calls)