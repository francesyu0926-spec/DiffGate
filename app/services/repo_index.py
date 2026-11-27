from datetime import datetime
from pathlib import Path

from git import Repo
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Repository
from app.engine.reverse_trace import ReverseTraceEngine
from app.graph.neo4j_contracts import Neo4jGlobalGraph
from app.graph.stores import Neo4jCallGraphStore, cache_adjacency
from app.parsers.http_client_scan import scan_repo_http_clients
from app.adapters.registry import cache_ir, index_repository_graph, normalize_repo_type, repo_type_index_supported
from app.services.frontend_index_cache import scan_and_cache_frontend
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

    rtype = normalize_repo_type(repo.repo_type)
    is_frontend = rtype == "frontend"
    method_count = 0
    api_count = 0
    symbols = []
    graph = None

    if is_frontend:
        fe_payload = scan_and_cache_frontend(repo_dir, repo.id, scan_root=scan_root, repo=repo)
        api_count = len(fe_payload.get("api_calls") or [])
        method_count = len(fe_payload.get("components") or [])
        if settings.use_neo4j:
            from app.parsers.vue_ts_index import scan_frontend_repo

            roots = (scan_root,) if scan_root not in (".", "") else ("src", "web", "frontend", ".")
            idx = scan_frontend_repo(repo_dir, scan_roots=roots)
            store = Neo4jCallGraphStore()
            try:
                global_graph = Neo4jGlobalGraph(store)
                global_graph.purge_legacy_repo_symbols(repo.full_name)
                global_graph.purge_repo_scoped_nodes(repo.id)
                global_graph.upsert_repository(repo_id=repo.id, full_name=repo.full_name)
                global_graph.sync_frontend_contracts(
                    repo_id=repo.id,
                    index=idx,
                    api_base_prefix=repo.api_base_prefix or "",
                )
            finally:
                store.close()
    elif rtype == "backend_node":
        ir = index_repository_graph(
            repo_type=rtype,
            repo_id=repo.id,
            repo_full_name=repo.full_name,
            repo_dir=repo_dir,
            scan_root=scan_root,
        )
        if ir:
            cache_ir(repo.id, ir)
        method_count = len(ir.symbols) if ir else 0
        api_count = len(ir.endpoints) if ir else 0
    elif not repo_type_index_supported(repo.repo_type):
        raise ValueError(
            f"仓库类型 {rtype} 的全量 AST 索引尚未开放，请在仓库管理中改为 Python / 前端类型，或等待后续版本。"
        )
    else:
        engine = ReverseTraceEngine()
        symbols, graph = engine.step1_index(repo_dir, scan_root=scan_root)
        method_count = sum(1 for s in symbols if s.kind in ("function", "method"))
        api_count = sum(1 for s in symbols if s.is_api_handler)
        ir = index_repository_graph(
            repo_type=rtype,
            repo_id=repo.id,
            repo_full_name=repo.full_name,
            repo_dir=repo_dir,
            scan_root=scan_root,
        )
        if ir:
            cache_ir(repo.id, ir)

        cache_adjacency(repo.full_name, graph)
        if settings.use_neo4j:
            store = Neo4jCallGraphStore()
            try:
                http_hits = scan_repo_http_clients(repo_dir, repo.full_name, scan_root=scan_root)
                store.upsert_http_client_edges(repo.full_name, http_hits)
                global_graph = Neo4jGlobalGraph(store)
                global_graph.purge_legacy_repo_symbols(repo.full_name)
                global_graph.purge_repo_scoped_nodes(repo.id)
                global_graph.upsert_repository(repo_id=repo.id, full_name=repo.full_name)
                global_graph.sync_symbol_calls(repo_id=repo.id, symbols=symbols, graph=graph, replace_calls=True)
                global_graph.sync_api_contracts(repo_id=repo.id, full_name=repo.full_name, symbols=symbols)
                global_graph.sync_http_consumers(repo_id=repo.id, full_name=repo.full_name, hits=http_hits)
            finally:
                store.close()

    repo.ast_method_count = method_count
    repo.ast_api_count = api_count
    repo.last_indexed_at = datetime.utcnow()
    db.commit()
    db.refresh(repo)

    if (repo.repo_type or "backend") == "frontend":
        from app.services.contract_gate_refresh import refresh_linked_backend_contract_gates

        refresh_linked_backend_contract_gates(db, frontend_repo=repo)

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