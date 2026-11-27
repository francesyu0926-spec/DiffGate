"""Neo4j 跨仓 Contract / APIEndpoint / CONSUMES 图谱（与单仓 Symbol 图并存）。"""

from __future__ import annotations

from app.parsers.frontend_contract import apply_api_base_prefix, frontend_call_confidence, normalize_frontend_api_path
from app.parsers.http_client_scan import _normalize_api_path, http_client_confidence, normalize_contract_path
from app.parsers.vue_ts_index import FrontendIndex
from app.graph.call_graph import CallGraph
from app.parsers.python_ast import SymbolDef


def contract_key_http(method: str, path: str) -> str:
    m = (method or "GET").upper()
    p = normalize_contract_path(path) or "/"
    return f"HTTP:{m}:{p}"


def symbol_uid(repo_id: str, file_path: str, qualname: str) -> str:
    return f"{repo_id}:{file_path}:{qualname}"


def resolve_symbol_uid(repo_id: str, qualname: str, symbols_by_name: dict[str, SymbolDef]) -> str:
    sym = symbols_by_name.get(qualname)
    if sym:
        return symbol_uid(repo_id, sym.file_path, sym.qualified_name)
    return symbol_uid(repo_id, "__external__", qualname)


def service_alias_from_repo(full_name: str) -> str:
    parts = full_name.split("/")
    return parts[-1] if parts else full_name


class Neo4jGlobalGraph:
    def __init__(self, store) -> None:
        self._store = store

    def purge_repo_scoped_nodes(self, repo_id: str) -> None:
        """全量重建前幂等清理：删除本仓节点，保留全局 :Contract。"""
        with self._store._driver.session() as session:
            session.run(
                """
                MATCH (r:Repository {repo_id: $repo_id})<-[:BELONGS_TO]-(n)
                WHERE NOT n:Contract
                DETACH DELETE n
                """,
                repo_id=repo_id,
            )

    def purge_legacy_repo_symbols(self, repo_full_name: str) -> None:
        """清理旧版 Symbol{repo,name} 节点，避免与 uid 模型并存。"""
        with self._store._driver.session() as session:
            session.run(
                "MATCH (s:Symbol {repo: $repo}) DETACH DELETE s",
                repo=repo_full_name,
            )

    def sync_symbol_calls(
        self,
        *,
        repo_id: str,
        symbols: list[SymbolDef],
        graph: CallGraph,
        replace_calls: bool = True,
        touch_files: set[str] | None = None,
    ) -> None:
        """统一写入 Symbol(uid) 与仓内 CALLS 边（与 APIEndpoint/Contract 模型共用节点）。"""
        by_name = {s.qualified_name: s for s in symbols}
        with self._store._driver.session() as session:
            for sym in symbols:
                uid = symbol_uid(repo_id, sym.file_path, sym.qualified_name)
                session.run(
                    """
                    MERGE (repo:Repository {repo_id: $repo_id})
                    MERGE (s:Symbol {uid: $uid})
                    SET s.repo_id = $repo_id, s.file_path = $file,
                        s.qualname = $qualname, s.kind = $kind,
                        s.start_line = $start, s.end_line = $end,
                        s.is_api = $is_api,
                        s.http_method = $method, s.route_path = $route
                    MERGE (s)-[:BELONGS_TO]->(repo)
                    """,
                    repo_id=repo_id,
                    uid=uid,
                    file=sym.file_path,
                    qualname=sym.qualified_name,
                    kind=sym.kind,
                    start=sym.start_line,
                    end=sym.end_line,
                    is_api=sym.is_api_handler,
                    method=sym.http_method or "",
                    route=sym.route_path or "",
                )
            if replace_calls:
                session.run(
                    """
                    MATCH (s:Symbol {repo_id: $repo_id})-[r:CALLS]->()
                    DELETE r
                    """,
                    repo_id=repo_id,
                )
            elif touch_files:
                norm = {p.replace("\\", "/") for p in touch_files if p}
                session.run(
                    """
                    MATCH (s:Symbol {repo_id: $repo_id})-[:CALLS]-(o)
                    WHERE s.file_path IN $files
                    MATCH (s)-[r:CALLS]-(o)
                    DELETE r
                    """,
                    repo_id=repo_id,
                    files=sorted(norm),
                )
            for caller, callees in graph.forward.items():
                caller_uid = resolve_symbol_uid(repo_id, caller, by_name)
                for callee in callees:
                    callee_uid = resolve_symbol_uid(repo_id, callee, by_name)
                    session.run(
                        """
                        MERGE (a:Symbol {uid: $caller_uid})
                        MERGE (b:Symbol {uid: $callee_uid})
                        ON CREATE SET b.repo_id = $repo_id, b.kind = 'external',
                            b.qualname = $callee_name
                        MERGE (a)-[:CALLS]->(b)
                        """,
                        caller_uid=caller_uid,
                        callee_uid=callee_uid,
                        repo_id=repo_id,
                        callee_name=callee,
                    )

    def upsert_repository(self, *, repo_id: str, full_name: str) -> None:
        alias = service_alias_from_repo(full_name)
        with self._store._driver.session() as session:
            session.run(
                """
                MERGE (r:Repository {repo_id: $repo_id})
                SET r.name = $name, r.service_alias = $alias, r.full_name = $full_name
                """,
                repo_id=repo_id,
                name=full_name,
                alias=alias,
                full_name=full_name,
            )

    def sync_api_contracts(self, *, repo_id: str, full_name: str, symbols: list[SymbolDef]) -> None:
        with self._store._driver.session() as session:
            for sym in symbols:
                if not sym.is_api_handler or not sym.route_path:
                    continue
                method = (sym.http_method or "GET").upper()
                route = sym.route_path or "/"
                route_norm = normalize_contract_path(route)
                uid = f"{repo_id}:{method}:{route_norm}"
                sym_uid = symbol_uid(repo_id, sym.file_path, sym.qualified_name)
                ck = contract_key_http(method, route)
                session.run(
                    """
                    MERGE (repo:Repository {repo_id: $repo_id})
                    MERGE (ep:APIEndpoint {uid: $uid})
                    SET ep.repo_id = $repo_id, ep.http_method = $method,
                        ep.route_path = $route, ep.route_path_norm = $route_norm
                    MERGE (repo)<-[:BELONGS_TO]-(ep)
                    MERGE (c:Contract {contract_key: $ck})
                    SET c.type = 'HTTP', c.target_service = $alias
                    MERGE (ep)-[:PROVIDES {updated_at: timestamp()}]->(c)
                    MERGE (s:Symbol {uid: $sym_uid})
                    SET s.repo_id = $repo_id, s.file_path = $file,
                        s.qualname = $qualname, s.start_line = $start, s.end_line = $end
                    MERGE (repo)<-[:BELONGS_TO]-(s)
                    MERGE (ep)-[:EXPOSES]->(s)
                    """,
                    repo_id=repo_id,
                    uid=uid,
                    method=method,
                    route=route,
                    route_norm=route_norm,
                    ck=ck,
                    alias=service_alias_from_repo(full_name),
                    sym_uid=sym_uid,
                    file=sym.file_path,
                    qualname=sym.qualified_name,
                    start=sym.start_line,
                    end=sym.end_line,
                )

    def sync_frontend_contracts(
        self,
        *,
        repo_id: str,
        index: FrontendIndex,
        api_base_prefix: str = "",
    ) -> None:
        """前端仓：页面/模块 CONSUMES 契约 + 组件间 CALLS（import）。"""
        import_resolved: dict[str, set[str]] = {}
        for comp in index.components:
            resolved: set[str] = set()
            for spec in comp.imports:
                if spec.startswith("."):
                    base = comp.file_path.rsplit("/", 1)[0]
                    resolved.add(f"{base}/{spec}".replace("/./", "/"))
            import_resolved[comp.file_path] = resolved

        with self._store._driver.session() as session:
            for comp in index.components:
                page_uid = symbol_uid(repo_id, comp.file_path, f"page:{comp.file_path}")
                session.run(
                    """
                    MERGE (repo:Repository {repo_id: $repo_id})
                    MERGE (s:Symbol {uid: $uid})
                    SET s.repo_id = $repo_id, s.file_path = $file,
                        s.qualname = $qualname, s.kind = 'frontend_page',
                        s.node_role = 'frontend'
                    MERGE (s)-[:BELONGS_TO]->(repo)
                    """,
                    repo_id=repo_id,
                    uid=page_uid,
                    file=comp.file_path,
                    qualname=comp.file_path,
                )
                for call in comp.api_calls:
                    raw = apply_api_base_prefix(call.path, api_base_prefix)
                    norm = normalize_frontend_api_path(call.path, api_base_prefix=api_base_prefix)
                    ck = contract_key_http(call.method, norm)
                    conf = frontend_call_confidence(call.path)
                    call_uid = symbol_uid(repo_id, comp.file_path, f"fe_api:L{call.line}")
                    session.run(
                        """
                        MERGE (repo:Repository {repo_id: $repo_id})
                        MERGE (c:Contract {contract_key: $ck})
                        ON CREATE SET c.type = 'HTTP', c.target_service = 'backend'
                        MERGE (s:Symbol {uid: $uid})
                        SET s.repo_id = $repo_id, s.file_path = $file,
                            s.qualname = $label, s.kind = 'frontend_api_call',
                            s.node_role = 'frontend'
                        MERGE (s)-[:BELONGS_TO]->(repo)
                        MERGE (s)-[:CONSUMES {
                            call_type: 'frontend_fetch',
                            confidence: $confidence,
                            dynamic: $dynamic,
                            raw_path: $raw
                        }]->(c)
                        MERGE (page:Symbol {uid: $page_uid})
                        MERGE (page)-[:CALLS]->(s)
                        """,
                        repo_id=repo_id,
                        ck=ck,
                        uid=call_uid,
                        file=comp.file_path,
                        label=f"{call.method} {norm}",
                        confidence=conf,
                        dynamic=conf < 0.7,
                        raw=raw,
                        page_uid=page_uid,
                    )

    def sync_http_consumers(self, *, repo_id: str, full_name: str, hits: list) -> None:
        with self._store._driver.session() as session:
            for hit in hits:
                path = normalize_contract_path(hit.url_or_path)
                if not path:
                    continue
                method = (hit.method or "GET").upper()
                ck = contract_key_http(method, hit.url_or_path)
                sym_uid = f"{repo_id}:{hit.file_path}:L{hit.line}"
                confidence = http_client_confidence(hit.url_or_path)
                session.run(
                    """
                    MERGE (repo:Repository {repo_id: $repo_id})
                    MERGE (c:Contract {contract_key: $ck})
                    ON CREATE SET c.type = 'HTTP', c.target_service = 'unknown'
                    MERGE (s:Symbol {uid: $sym_uid})
                    SET s.repo_id = $repo_id, s.file_path = $file, s.qualname = $label
                    MERGE (repo)<-[:BELONGS_TO]-(s)
                    MERGE (s)-[:CONSUMES {
                        call_type: 'http_client',
                        confidence: $confidence,
                        dynamic: $dynamic
                    }]->(c)
                    """,
                    repo_id=repo_id,
                    ck=ck,
                    sym_uid=sym_uid,
                    file=hit.file_path,
                    label=f"http@{hit.line}",
                    confidence=confidence,
                    dynamic=confidence < 0.7,
                )

    def find_upstream_impact(
        self, contract_keys: list[str], *, depth: int = 3, exclude_repo_id: str | None = None
    ) -> list[dict]:
        if not contract_keys:
            return []
        hops = max(1, min(3, depth))
        rows: list[dict] = []
        with self._store._driver.session() as session:
            result = session.run(
                f"""
                MATCH (c:Contract)<-[:PROVIDES]-(provider:APIEndpoint)
                WHERE c.contract_key IN $keys
                MATCH (consumer:Symbol)-[:CONSUMES]->(c)
                WHERE ($exclude IS NULL OR consumer.repo_id <> $exclude)
                OPTIONAL MATCH (upstream_ep:APIEndpoint)-[:EXPOSES]->(consumer)
                OPTIONAL MATCH (up_repo:Repository)<-[:BELONGS_TO]-(upstream_ep)
                RETURN DISTINCT
                    c.contract_key AS contract_key,
                    provider.uid AS provider_endpoint,
                    consumer.repo_id AS consumer_repo_id,
                    consumer.file_path AS consumer_file,
                    consumer.qualname AS consumer_symbol,
                    length(path) AS hop_distance,
                    upstream_ep.uid AS upstream_endpoint,
                    upstream_ep.route_path AS upstream_route,
                    upstream_ep.http_method AS upstream_method,
                    up_repo.full_name AS upstream_repo
                LIMIT 80
                """,
                keys=contract_keys,
                exclude=exclude_repo_id,
            )
            for row in result:
                rows.append(dict(row))
        return rows

    def _merge_reverse_trace_rows(self, *parts: list[dict]) -> list[dict]:
        merged: list[dict] = []
        seen: set[tuple] = set()
        for part in parts:
            for row in part:
                key = (
                    row.get("api_uid"),
                    row.get("changed_uid"),
                    row.get("trace_kind"),
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(row)
        merged.sort(key=lambda r: (r.get("call_depth") or 999, r.get("api_uid") or ""))
        return merged[:120]

    def reverse_trace_changed_symbols(
        self, changed_symbol_uids: list[str], *, max_depth: int = 8
    ) -> list[dict]:
        """从变更 Symbol 逆向追溯：仓内 EXPOSES|CALLS + 跨仓 CONSUMES/PROVIDES。"""
        uids = [u for u in changed_symbol_uids if u]
        if not uids:
            return []
        depth = max(1, min(8, max_depth))
        local_rows: list[dict] = []
        cross_rows: list[dict] = []
        with self._store._driver.session() as session:
            local = session.run(
                f"""
                MATCH (changed:Symbol)
                WHERE changed.uid IN $uids
                MATCH path = (upstream_api:APIEndpoint)-[:EXPOSES|CALLS*1..{depth}]->(changed)
                MATCH (upstream_api)-[:BELONGS_TO]->(repo:Repository)
                RETURN DISTINCT
                  repo.repo_id AS repo_id,
                  repo.full_name AS repo_name,
                  upstream_api.uid AS api_uid,
                  upstream_api.http_method AS method,
                  upstream_api.route_path AS route_path,
                  changed.uid AS changed_uid,
                  length(path) AS call_depth,
                  'local' AS trace_kind,
                  null AS consume_confidence,
                  [n IN nodes(path) |
                    coalesce(n.qualname, n.route_path, n.uid)
                  ] AS trace_chain
                ORDER BY call_depth ASC
                LIMIT 80
                """,
                uids=uids,
            )
            for row in local:
                local_rows.append(dict(row))

            cross = session.run(
                f"""
                MATCH (changed:Symbol)
                WHERE changed.uid IN $uids
                MATCH call_path = (bridge:Symbol)-[:CALLS*0..{depth}]->(changed)
                MATCH (bridge)-[cons:CONSUMES]->(c:Contract)<-[:PROVIDES]-(upstream_api:APIEndpoint)
                MATCH (upstream_api)-[:BELONGS_TO]->(repo:Repository)
                RETURN DISTINCT
                  repo.repo_id AS repo_id,
                  repo.full_name AS repo_name,
                  upstream_api.uid AS api_uid,
                  upstream_api.http_method AS method,
                  upstream_api.route_path AS route_path,
                  changed.uid AS changed_uid,
                  length(call_path) + 2 AS call_depth,
                  'cross_repo' AS trace_kind,
                  cons.confidence AS consume_confidence,
                  [n IN nodes(call_path) | coalesce(n.qualname, n.uid)]
                    + [c.contract_key]
                    + [coalesce(upstream_api.http_method + ' ' + upstream_api.route_path, upstream_api.uid)]
                    AS trace_chain
                ORDER BY call_depth ASC
                LIMIT 80
                """,
                uids=uids,
            )
            for row in cross:
                cross_rows.append(dict(row))

        return self._merge_reverse_trace_rows(local_rows, cross_rows)