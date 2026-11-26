"""tree-sitter 语言加载（TypeScript / TSX / JavaScript）。"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Parser


@lru_cache
def typescript_parser() -> Parser | None:
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_typescript as tst

        lang = Language(tst.language_typescript())
        return Parser(lang)
    except Exception:
        return None


@lru_cache
def tsx_parser() -> Parser | None:
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_typescript as tst

        lang = Language(tst.language_tsx())
        return Parser(lang)
    except Exception:
        return None


@lru_cache
def javascript_parser() -> Parser | None:
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_javascript as tsj

        lang = Language(tsj.language())
        return Parser(lang)
    except Exception:
        return None


def parser_for_path(path: str) -> Parser | None:
    low = path.lower()
    if low.endswith(".tsx"):
        return tsx_parser()
    if low.endswith((".ts", ".mts", ".cts")):
        return typescript_parser()
    if low.endswith((".js", ".jsx", ".mjs", ".cjs")):
        return javascript_parser()
    return typescript_parser()