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

    def upsert_repo_graph(self, repo_key: str, symbols: list[SymbolDef], graph: CallGraph) -> None:
        with self._driver.session() as session:
            session.run("MATCH (n:Symbol {repo: $repo}) DETACH DELETE n", repo=repo_key)
            for sym in symbols:
                session.run(
                    """
                    CREATE (s:Symbol {
                        repo: $repo,
                        name: $name,
                        file: $file,
                        kind: $kind,
                        start: $start,
                        end: $end,
                        is_api: $is_api,
                        method: $method,
                        route: $route
                    })
                    """,
                    repo=repo_key,
                    name=sym.qualified_name,
                    file=sym.file_path,
                    kind=sym.kind,
                    start=sym.start_line,
                    end=sym.end_line,
                    is_api=sym.is_api_handler,
                    method=sym.http_method,
                    route=sym.route_path,
                )
            for caller, callees in graph.forward.items():
                for callee in callees:
                    session.run(
                        """
                        MATCH (a:Symbol {repo: $repo, name: $caller})
                        MERGE (b:Symbol {repo: $repo, name: $callee})
                        ON CREATE SET b.kind = 'external'
                        MERGE (a)-[:CALLS]->(b)
                        """,
                        repo=repo_key,
                        caller=caller,
                        callee=callee,
                    )