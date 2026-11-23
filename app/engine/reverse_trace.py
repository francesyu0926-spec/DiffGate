from dataclasses import dataclass, field
from pathlib import Path

from app.graph.call_graph import CallGraph
from app.graph.stores import Neo4jCallGraphStore, cache_adjacency, cache_job_graph
from app.graph.viz import build_g6_payload
from app.parsers.python_ast import SymbolDef, scan_python_repo
from app.parsers.git_diff import LineRange, get_changed_line_ranges, summarize_diff


@dataclass
class SuspectFunction:
    qualified_name: str
    file_path: str
    start_line: int
    end_line: int
    changed_lines: list[int] = field(default_factory=list)


@dataclass
class ImpactReport:
    """第四步：影响面报告（接口清单 + 拓扑路径）。"""

    suspect_functions: list[SuspectFunction]
    affected_apis: list[dict]
    call_paths: list[dict]
    line_ranges: list[LineRange]
    symbol_count: int
    reverse_edge_count: int
    diff_summary: dict

    def to_dict(self) -> dict:
        return {
            "suspect_functions": [
                {
                    "qualified_name": s.qualified_name,
                    "file": s.file_path,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                    "changed_lines": s.changed_lines,
                }
                for s in self.suspect_functions
            ],
            "affected_apis": self.affected_apis,
            "call_paths": self.call_paths,
            "line_ranges": [
                {"path": r.path, "start": r.start, "end": r.end} for r in self.line_ranges
            ],
            "stats": {
                "symbol_count": self.symbol_count,
                "reverse_edge_count": self.reverse_edge_count,
                "api_count": len(self.affected_apis),
            },
            "diff_summary": self.diff_summary,
        }


class ReverseTraceEngine:
    """
    基于 AST 的逆向接口追溯引擎。

    第一步：全量扫描 + 反向索引（谁调用了我）
    第二步：Git Diff 定位变更行 → 嫌疑函数
    第三步：反向图 BFS（Visited Set 防环）
    第四步：输出 API 清单与 call path，供前端 G6 / 调度中心消费
    """

    def step1_index(self, repo_root: Path, scan_root: str = ".") -> tuple[list[SymbolDef], CallGraph]:
        symbols = scan_python_repo(repo_root, scan_root=scan_root)
        graph = CallGraph()
        graph.add_symbols(symbols)
        return symbols, graph

    @staticmethod
    def _symbols_covering_line(symbols: list[SymbolDef], path: str, line: int) -> list[str]:
        out: list[str] = []
        for sym in symbols:
            if sym.file_path != path or sym.kind == "class":
                continue
            if sym.start_line <= line <= sym.end_line:
                out.append(sym.qualified_name)
        return out

    def step2_locate_suspects(
        self, symbols: list[SymbolDef], line_ranges: list[LineRange]
    ) -> list[SuspectFunction]:
        meta: dict[str, tuple[SymbolDef, set[int]]] = {}
        sym_index = {s.qualified_name: s for s in symbols}

        for lr in line_ranges:
            for line in range(lr.start, lr.end + 1):
                for qname in self._symbols_covering_line(symbols, lr.path, line):
                    sym = sym_index[qname]
                    if qname not in meta:
                        meta[qname] = (sym, {line})
                    else:
                        meta[qname][1].add(line)

        if not meta and line_ranges:
            for lr in line_ranges:
                for sym in symbols:
                    if sym.file_path == lr.path and sym.kind != "class":
                        meta.setdefault(sym.qualified_name, (sym, set()))

        return [
            SuspectFunction(
                qualified_name=qname,
                file_path=sym.file_path,
                start_line=sym.start_line,
                end_line=sym.end_line,
                changed_lines=sorted(lines),
            )
            for qname, (sym, lines) in sorted(meta.items())
        ]

    def step3_reverse_bfs(self, graph: CallGraph, suspects: list[SuspectFunction]) -> list[dict]:
        seed = {s.qualified_name for s in suspects}
        return graph.reverse_bfs_traces(seed)

    def step4_report(
        self,
        suspects: list[SuspectFunction],
        traces: list[dict],
        line_ranges: list[LineRange],
        graph: CallGraph,
        diff_summary: dict,
    ) -> ImpactReport:
        apis = [
            {
                "handler": t["handler"],
                "method": t["method"],
                "path": t["path"],
                "file": t["file"],
                "line": t["line"],
            }
            for t in traces
        ]
        call_paths = [
            {
                "method": t["method"],
                "path": t["path"],
                "chain": t["chain_labels"],
                "chain_full": t["chain"],
                "layers": t["layers"],
            }
            for t in traces
        ]
        return ImpactReport(
            suspect_functions=suspects,
            affected_apis=apis,
            call_paths=call_paths,
            line_ranges=line_ranges,
            symbol_count=len(graph.symbols),
            reverse_edge_count=sum(len(v) for v in graph.reverse.values()),
            diff_summary=diff_summary,
        )

    def run(
        self,
        repo_path: Path,
        base_sha: str,
        head_sha: str,
        repo_key: str,
        *,
        use_neo4j: bool,
        job_id: str | None = None,
        scan_root: str = ".",
    ) -> ImpactReport:
        diff_summary = summarize_diff(repo_path, base_sha, head_sha)
        line_ranges = get_changed_line_ranges(repo_path, base_sha, head_sha)

        symbols, graph = self.step1_index(repo_path, scan_root=scan_root)
        cache_adjacency(repo_key, graph)

        suspects = self.step2_locate_suspects(symbols, line_ranges)
        traces = self.step3_reverse_bfs(graph, suspects)
        report = self.step4_report(suspects, traces, line_ranges, graph, diff_summary)

        if job_id:
            suspect_names = [s.qualified_name for s in suspects]
            cache_job_graph(job_id, build_g6_payload(graph, suspect_names))

        if use_neo4j:
            store = Neo4jCallGraphStore()
            try:
                store.upsert_repo_graph(repo_key, symbols, graph)
            finally:
                store.close()

        return report