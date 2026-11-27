"""探针命中与 AST 多行语句对齐（装饰器由 L3 statements 白名单兜底）。"""

from __future__ import annotations

import ast
from pathlib import Path

_MULTILINE_STMT_TYPES = (
    ast.Call,
    ast.Return,
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.Expr,
    ast.Await,
    ast.Raise,
    ast.Assert,
)


def load_sources(repo_dir: Path, rel_paths: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in rel_paths:
        fp = repo_dir / rel
        if not fp.is_file():
            continue
        try:
            out[rel] = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return out


def propagate_multiline_hits(
    effective: set[tuple[str, int]],
    executed: set[tuple[str, int]],
    sources: dict[str, str],
) -> set[tuple[str, int]]:
    """
    多行语句：若 coverage 命中块首行 (lineno)，则同块内其它变更行视为已覆盖。
    """
    expanded = set(executed)
    by_file: dict[str, set[int]] = {}
    for path, ln in effective:
        by_file.setdefault(path, set()).add(ln)

    for path, source in sources.items():
        eff_lines = by_file.get(path)
        if not eff_lines:
            continue
        hit_lines = {ln for p, ln in executed if p == path}
        if not hit_lines:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, _MULTILINE_STMT_TYPES):
                continue
            start = getattr(node, "lineno", None)
            if start is None:
                continue
            end = getattr(node, "end_lineno", start) or start
            if end <= start:
                continue
            if start not in hit_lines:
                continue
            for ln in range(start, end + 1):
                if ln in eff_lines:
                    expanded.add((path, ln))
    return expanded