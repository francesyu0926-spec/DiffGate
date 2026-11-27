import json

from app.config import get_settings
from app.graph.call_graph import CallGraph
from app.graph import local_cache
from app.parsers.python_ast import SymbolDef


def _redis_client():
    import redis

    return redis.from_url(get_settings().redis_url, decode_responses=True)


def cache_job_graph(job_id: str, payload: dict) -> None:
    if get_settings().use_redis:
        client = _redis_client()
        client.set(f"job:{job_id}:graph", json.dumps(payload), ex=86400 * 7)
    else:
        local_cache.write_json(f"jobs/{job_id}/graph.json", payload)


def load_job_graph(job_id: str) -> dict | None:
    if get_settings().use_redis:
        client = _redis_client()
        raw = client.get(f"job:{job_id}:graph")
        if not raw:
            return None
        return json.loads(raw)
    return local_cache.read_json(f"jobs/{job_id}/graph.json")


def cache_adjacency(repo_key: str, graph: CallGraph) -> None:
    """Persist reverse adjacency list (Redis or local file)."""
    payload = {
        "reverse": {k: sorted(v) for k, v in graph.reverse.items() if v},
        "apis": graph.affected_apis(set()),
    }
    if get_settings().use_redis:
        client = _redis_client()
        pipe = client.pipeline()
        prefix = f"cg:{repo_key}:rev"
        pipe.delete(prefix)
        for callee, callers in graph.reverse.items():
            if callers:
                pipe.hset(prefix, callee, json.dumps(sorted(callers)))
        pipe.set(f"cg:{repo_key}:apis", json.dumps(payload["apis"]))
        pipe.execute()
    else:
        safe = repo_key.replace("/", "_")
        local_cache.write_json(f"cg/{safe}/adjacency.json", payload)


class Neo4jCallGraphStore:
    def __init__(self) -> None:
        from neo4j import GraphDatabase

        s = get_settings()
        self._driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))

    def close(self) -> None:
        self._driver.close()

    def upsert_repo_graph(
        self,
        repo_key: str,
        symbols: list[SymbolDef],
        graph: CallGraph,
        *,
        repo_id: str | None = None,
        replace_calls: bool = False,
        touch_files: set[str] | None = None,
    ) -> None:
        """写入统一 uid Symbol + CALLS；需传入 repo_id（与 Repository 主键一致）。"""
        if not repo_id:
            return
        from app.graph.neo4j_contracts import Neo4jGlobalGraph

        Neo4jGlobalGraph(self).sync_symbol_calls(
            repo_id=str(repo_id),
            symbols=symbols,
            graph=graph,
            replace_calls=replace_calls,
            touch_files=touch_files,
        )

    def upsert_provider_routes(self, provider_repo: str, apis: list[dict]) -> None:
        """跨仓图：提供方 API 路由节点。"""
        with self._driver.session() as session:
            for api in apis:
                if not isinstance(api, dict):
                    continue
                path = api.get("path") or "/"
                method = (api.get("method") or "GET").upper()
                session.run(
                    """
                    MERGE (r:ApiRoute {provider_repo: $repo, path: $path, method: $method})
                    SET r.file = $file, r.updated_at = timestamp()
                    """,
                    repo=provider_repo,
                    path=path,
                    method=method,
                    file=api.get("file"),
                )

    def upsert_http_client_edges(self, consumer_repo: str, hits: list) -> None:
        """跨仓图：消费方 HTTP 调用边。"""
        from app.parsers.http_client_scan import _normalize_api_path

        with self._driver.session() as session:
            session.run(
                "MATCH (h:HttpCall {consumer_repo: $repo}) DETACH DELETE h",
                repo=consumer_repo,
            )
            for hit in hits:
                path = _normalize_api_path(hit.url_or_path)
                if not path:
                    continue
                session.run(
                    """
                    CREATE (h:HttpCall {
                        consumer_repo: $consumer,
                        file: $file,
                        line: $line,
                        method: $method,
                        needle: $needle
                    })
                    WITH h
                    OPTIONAL MATCH (r:ApiRoute)
                    WHERE r.path = $path OR r.path ENDS WITH $path
                    MERGE (h)-[:MAY_CALL]->(r)
                    """,
                    consumer=consumer_repo,
                    file=hit.file_path,
                    line=hit.line,
                    method=(hit.method or "GET").upper(),
                    needle=path,
                    path=path,
                )

    def find_consumers_for_paths(
        self, paths: list[str], *, exclude_repo: str | None = None
    ) -> list[dict]:
        from app.parsers.http_client_scan import _normalize_api_path

        needles = sorted({_normalize_api_path(p) for p in paths if p})
        if not needles:
            return []
        out: list[dict] = []
        with self._driver.session() as session:
            for needle in needles:
                rows = session.run(
                    """
                    MATCH (h:HttpCall)-[:MAY_CALL]->(r:ApiRoute)
                    WHERE h.needle = $needle OR r.path = $needle OR r.path ENDS WITH $needle
                    RETURN h.consumer_repo AS consumer_repo, h.file AS file, h.line AS line,
                           h.method AS method, h.needle AS url_or_path, r.provider_repo AS provider_repo
                    LIMIT 30
                    """,
                    needle=needle,
                )
                for row in rows:
                    if exclude_repo and row.get("consumer_repo") == exclude_repo:
                        continue
                    out.append(dict(row))
        return out