import shutil
from datetime import datetime
from pathlib import Path

from git import Repo
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Repository
from app.engine.reverse_trace import ReverseTraceEngine
from app.graph.stores import Neo4jCallGraphStore, cache_adjacency
from app.services.git_clone import clone_repository


def _repo_dir(full_name: str) -> Path:
    settings = get_settings()
    safe = full_name.replace("/", "_")
    return Path(settings.repo_clone_root) / safe


def reindex_repository(db: Session, repo: Repository) -> dict:
    settings = get_settings()
    repo_dir = _repo_dir(repo.full_name)
    if repo_dir.exists():
        shutil.rmtree(repo_dir, ignore_errors=True)
    clone_repository(repo, repo_dir, branch=repo.default_branch, depth=1)

    engine = ReverseTraceEngine()
    symbols, graph = engine.step1_index(repo_dir, scan_root=repo.scan_root or ".")
    method_count = sum(1 for s in symbols if s.kind in ("function", "method"))
    api_count = sum(1 for s in symbols if s.is_api_handler)

    cache_adjacency(repo.full_name, graph)
    if settings.use_neo4j:
        store = Neo4jCallGraphStore()
        try:
            store.upsert_repo_graph(repo.full_name, symbols, graph)
        finally:
            store.close()

    repo.ast_method_count = method_count
    repo.ast_api_count = api_count
    repo.last_indexed_at = datetime.utcnow()
    db.commit()
    db.refresh(repo)

    return {
        "method_count": method_count,
        "api_count": api_count,
        "symbol_count": len(symbols),
        "indexed_at": repo.last_indexed_at.isoformat() if repo.last_indexed_at else None,
    }


def resolve_head_shas(repo: Repository) -> tuple[str, str]:
    repo_dir = _repo_dir(repo.full_name)
    if not repo_dir.is_dir():
        clone_repository(repo, repo_dir, branch=repo.default_branch, depth=50)
    git = Repo(str(repo_dir))
    head = git.head.commit
    head_sha = head.hexsha
    parents = head.parents
    base_sha = parents[0].hexsha if parents else head_sha
    return base_sha, head_sha