"""Python / FastAPI 适配器。"""

from __future__ import annotations

from pathlib import Path

from app.adapters.protocol import RepoGraphIR
from app.engine.reverse_trace import ReverseTraceEngine
from app.graph.neo4j_contracts import symbol_uid


def index_python(
    *,
    repo_id: str,
    repo_full_name: str,
    repo_dir: Path,
    scan_root: str,
) -> RepoGraphIR:
    engine = ReverseTraceEngine()
    symbols, graph = engine.step1_index(repo_dir, scan_root=scan_root)
    return RepoGraphIR.from_python_index(
        repo_id=repo_id,
        repo_full_name=repo_full_name,
        symbols=symbols,
        graph=graph,
        uid_fn=symbol_uid,
    )