"""基于 ast + tokenize 提取 Python 文件有效可执行行号。"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

_IGNORED_TOKEN_TYPES = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
)

_PY_TEST_DIR_PARTS = frozenset({"tests", "test", "migrations", "scripts", "__pycache__"})


def get_effective_executable_lines(
    source_code: str,
    *,
    ignore_imports: bool = True,
    ignore_type_annotations: bool = True,
) -> set[int]:
    """
    从 Python 源码中提取「有效可执行行号」集合（1-based 行号）。
    自动剔除：
      1. 空行、纯空白行、单行/行尾注释（tokenize 层）
      2. 模块 / 类 / 函数 Docstrings
      3. pass / … (Ellipsis) 占位语句
      4. (可选) import / from … import
      5. (可选) 纯类型注解 AnnAssign（无赋值右侧）
    """
    if not source_code or not source_code.strip():
        return set()

    non_comment_code_lines: set[int] = set()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source_code).readline)
        for tok in tokens:
            if tok.type in _IGNORED_TOKEN_TYPES:
                continue
            start_line = tok.start[0]
            end_line = tok.end[0]
            for line_no in range(start_line, end_line + 1):
                non_comment_code_lines.add(line_no)
    except tokenize.TokenError:
        for idx, line in enumerate(source_code.splitlines(), start=1):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                non_comment_code_lines.add(idx)

    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return non_comment_code_lines

    excluded_lines: set[int] = set()

    def _mark_node_lines(node: ast.AST) -> None:
        """整段剔除（lineno…end_lineno），兼容多行 import(...) 与多行 \"\"\"doc\"\"\"。 """
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", start)
        if start is not None and end is not None:
            for ln in range(start, end + 1):
                excluded_lines.add(ln)

    def _extract_docstring(body: list[ast.stmt]) -> None:
        if not body:
            return
        first_stmt = body[0]
        if (
            isinstance(first_stmt, ast.Expr)
            and isinstance(first_stmt.value, ast.Constant)
            and isinstance(first_stmt.value.value, str)
        ):
            _mark_node_lines(first_stmt)

    _extract_docstring(tree.body)

    def _is_type_checking_if(node: ast.AST) -> bool:
        if not isinstance(node, ast.If):
            return False
        test = node.test
        if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
            return True
        if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
            return True
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_if(node):
            _mark_node_lines(node)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            _extract_docstring(node.body)
        elif isinstance(node, ast.Pass):
            _mark_node_lines(node)
        elif isinstance(node, ast.Expr):
            val = node.value
            if isinstance(val, ast.Constant) and val.value is Ellipsis:
                _mark_node_lines(node)
            elif isinstance(val, ast.Ellipsis):
                _mark_node_lines(node)
        elif ignore_imports and isinstance(node, (ast.Import, ast.ImportFrom)):
            _mark_node_lines(node)
        elif ignore_type_annotations and isinstance(node, ast.AnnAssign) and node.value is None:
            _mark_node_lines(node)

    return non_comment_code_lines - excluded_lines


def effective_executable_lines_from_path(
    file_path: Path,
    *,
    ignore_imports: bool = True,
    ignore_type_annotations: bool = True,
) -> set[int]:
    """读盘并返回有效可执行行号；文件不存在时返回空集。"""
    if not file_path.is_file():
        return set()
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return get_effective_executable_lines(
        source,
        ignore_imports=ignore_imports,
        ignore_type_annotations=ignore_type_annotations,
    )


def filter_diff_changed_lines(
    file_path: str,
    source_code: str,
    git_diff_added_lines: set[int],
    *,
    ignore_imports: bool = True,
    ignore_type_annotations: bool = True,
) -> dict[str, list[int]]:
    """
    结合 Git Diff 新增/修改行号，输出清洗后的分母与被过滤行明细。
    """
    p = Path(file_path.replace("\\", "/"))
    if (
        p.suffix != ".py"
        or p.name.startswith("test_")
        or p.name.endswith("_test.py")
        or any(part in _PY_TEST_DIR_PARTS for part in p.parts)
    ):
        return {
            "effective_lines": [],
            "ignored_lines": sorted(git_diff_added_lines),
        }

    executable_set = get_effective_executable_lines(
        source_code,
        ignore_imports=ignore_imports,
        ignore_type_annotations=ignore_type_annotations,
    )
    effective = sorted(git_diff_added_lines & executable_set)
    ignored = sorted(git_diff_added_lines - executable_set)
    return {
        "effective_lines": effective,
        "ignored_lines": ignored,
    }