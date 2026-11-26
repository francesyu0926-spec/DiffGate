"""语义 AST 哈希：忽略注释/空白与行号漂移，用于纯格式化 diff 降噪。"""

from __future__ import annotations

import ast
import hashlib


def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if not body:
        return body
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(
        first.value.value, str
    ):
        return body[1:]
    return body


def _normalize_node(node: ast.AST) -> str:
    """用 ast.dump 去掉位置信息，得到稳定结构串。"""

    def scrub(n: ast.AST) -> ast.AST:
        for field, value in ast.iter_fields(n):
            if field in ("lineno", "col_offset", "end_lineno", "end_col_offset"):
                continue
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        scrub(item)
            elif isinstance(value, ast.AST):
                scrub(value)
        return n

    scrub(node)
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def function_body_hash(source: str, qualified_suffix: str) -> str | None:
    """按 qualified_name 尾段（如 module.Class.fn）在源码中定位函数并算哈希。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    target = qualified_suffix.split(".")[-1]
    stack: list[str] = []

    class Finder(ast.NodeVisitor):
        found: str | None = None

        def _handle_fn(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            qparts = stack + [node.name]
            qname = ".".join(qparts)
            if qname == qualified_suffix or (not stack and node.name == target):
                body = _strip_docstring(list(node.body))
                mini = ast.Module(body=body, type_ignores=[])
                ast.fix_missing_locations(mini)
                self.found = _normalize_node(mini)
                return
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._handle_fn(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._handle_fn(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

    finder = Finder()
    finder.visit(tree)
    if not finder.found:
        return None
    return hashlib.sha256(finder.found.encode("utf-8")).hexdigest()[:16]