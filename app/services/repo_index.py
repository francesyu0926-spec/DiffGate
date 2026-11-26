from datetime import datetime
from pathlib import Path

from git import Repo
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Repository
from app.engine.reverse_trace import ReverseTraceEngine
from app.graph.stores import Neo4jCallGraphStore, cache_adjacency
from app.services.git_clone import clear_clone_dest, clone_repository


def _repo_dir(full_name: str) -> Path:
    settings = get_settings()
    safe = full_name.replace("/", "_")
    return Path(settings.repo_clone_root) / safe


def _resolve_scan_root(repo_dir: Path, scan_root: str) -> tuple[str, bool]:
    """
    若配置 scan_root 扫不到 Python，且仍为默认值 '.'，尝试常见后端目录（如 QuantLens/backend）。
    返回 (有效 scan_root, 是否自动修正)。
    """
    from app.parsers.python_ast import scan_python_repo

    root = (scan_root or ".").strip() or "."
    symbols = scan_python_repo(repo_dir, root)
    if symbols:
        return root, False
    if root not in (".", ""):
        return root, False
    best_root = root
    best_n = 0
    for candidate in ("backend", "src", "server", "api", "services"):
        sub = repo_dir / candidate
        if not sub.is_dir():
            continue
        n = len(scan_python_repo(repo_dir, candidate))
        if n > best_n:
            best_n = n
            best_root = candidate
    if best_n > 0:
        return best_root, True
    return root, False


def reindex_repository(db: Session, repo: Repository) -> dict:
    settings = get_settings()
    repo_dir = _repo_dir(repo.full_name).resolve()
    clear_clone_dest(repo_dir)
    clone_repository(repo, repo_dir, branch=repo.default_branch, depth=1)

    scan_root, auto_fixed = _resolve_scan_root(repo_dir, repo.scan_root or ".")
    if auto_fixed and (repo.scan_root or ".") in (".", ""):
        repo.scan_root = scan_root

    engine = ReverseTraceEngine()
    symbols, graph = engine.step1_index(repo_dir, scan_root=scan_root)
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
    repo_dir = _repo_dir(repo.full_name).resolve()
    if not (repo_dir / ".git").is_dir():
        clear_clone_dest(repo_dir)
        clone_repository(repo, repo_dir, branch=repo.default_branch, depth=50)
    git = Repo(str(repo_dir))
    head = git.head.commit
    head_sha = head.hexsha
    parents = head.parents
    base_sha = parents[0].hexsha if parents else head_sha
    return base_sha, head_sha