from collections import defaultdict, deque

from app.parsers.python_ast import SymbolDef


class CallGraph:
    """Forward calls and reverse callers adjacency lists."""

    def __init__(self) -> None:
        self.forward: dict[str, set[str]] = defaultdict(set)
        self.reverse: dict[str, set[str]] = defaultdict(set)
        self.symbols: dict[str, SymbolDef] = {}
        self.apis: dict[str, SymbolDef] = {}

    def add_symbols(self, symbols: list[SymbolDef]) -> None:
        for sym in symbols:
            self.symbols[sym.qualified_name] = sym
            if sym.is_api_handler:
                api_id = f"{sym.http_method or 'GET'} {sym.route_path or '/'}"
                self.apis[sym.qualified_name] = sym

            caller = sym.qualified_name
            for callee in sym.calls:
                self.forward[caller].add(callee)
                self.reverse[callee].add(caller)
                short = callee.split(".")[-1]
                if short != callee:
                    self.reverse[short].add(caller)

    def _canonical(self, node: str) -> str:
        if node in self.symbols:
            return node
        short = node.split(".")[-1]
        if short in self.symbols:
            return short
        matches = [
            n
            for n in self.symbols
            if n == node or n.endswith(f".{node}") or n.split(".")[-1] == short
        ]
        if len(matches) == 1:
            return matches[0]
        return node

    def _reverse_neighbors(self, node: str) -> set[str]:
        node = self._canonical(node)
        keys = {node, node.split(".")[-1]}
        sym = self.symbols.get(node)
        if sym:
            keys.add(sym.qualified_name)
        callers: set[str] = set()
        for key in keys:
            callers.update(self.reverse.get(key, ()))
        return {self._canonical(c) for c in callers}

    def resolve_callers(self, seed: set[str]) -> set[str]:
        """第三步：反向 BFS，Visited Set 避免环/递归死循环。"""
        visited: set[str] = set()
        queue: deque[str] = deque(seed)
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            for parent in self._reverse_neighbors(node):
                if parent not in visited:
                    queue.append(parent)
        return visited

    def _rebuild_chain(self, api_node: str, parent: dict[str, str | None]) -> list[str]:
        chain: list[str] = []
        cur: str | None = self._canonical(api_node)
        seen: set[str] = set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            nxt = parent.get(cur)
            if nxt is None:
                short = cur.split(".")[-1]
                for alt in (short, self._canonical(cur)):
                    nxt = parent.get(alt)
                    if nxt is not None:
                        break
            cur = self._canonical(nxt) if nxt else None
        chain.reverse()
        return chain

    def _hop_depth(self, api_node: str, parent: dict[str, str | None]) -> int:
        return max(0, len(self._rebuild_chain(api_node, parent)) - 1)

    def _label(self, qname: str) -> str:
        sym = self.symbols.get(qname)
        if sym and sym.is_api_handler:
            method = (sym.http_method or "GET").upper()
            return f"{method} {sym.route_path or '/'}"
        return qname.split(".")[-1]

    def reverse_bfs_traces(self, suspect_qnames: set[str]) -> list[dict]:
        """从嫌疑函数反向 BFS 至顶层 API，并输出最短调用链路径。"""
        seeds = self._expand_seeds(suspect_qnames)
        visited: set[str] = set()
        queue: deque[str] = deque()
        parent: dict[str, str | None] = {}

        for s in seeds:
            seed = self._canonical(s)
            if seed not in parent:
                parent[seed] = None
                queue.append(seed)

        traces: list[dict] = []
        seen_api: set[str] = set()

        while queue:
            node = self._canonical(queue.popleft())
            if node in visited:
                continue
            visited.add(node)

            sym = self.symbols.get(node)
            if sym and sym.is_api_handler:
                api_key = f"{sym.http_method}:{sym.route_path}:{node}"
                if api_key not in seen_api:
                    seen_api.add(api_key)
                    chain = self._rebuild_chain(node, parent)
                    hops = self._hop_depth(node, parent)
                    traces.append(
                        {
                            "handler": node,
                            "method": (sym.http_method or "GET").upper(),
                            "path": sym.route_path or "/",
                            "file": sym.file_path,
                            "line": sym.start_line,
                            "chain": chain,
                            "chain_labels": [self._label(x) for x in chain],
                            "layers": hops,
                        }
                    )

            for caller in self._reverse_neighbors(node):
                caller = self._canonical(caller)
                if caller in visited:
                    continue
                if caller not in parent:
                    parent[caller] = node
                    queue.append(caller)

        return sorted(traces, key=lambda t: (t["path"], t["method"]))

    def _expand_seeds(self, seeds: set[str]) -> set[str]:
        expanded = set(seeds)
        for name in seeds:
            expanded.add(name.split(".")[-1])
            sym = self.symbols.get(name)
            if sym:
                expanded.add(sym.qualified_name)
        return expanded

    def affected_apis(self, changed_qualified: set[str]) -> list[dict]:
        return [
            {k: t[k] for k in ("handler", "method", "path", "file", "line")}
            for t in self.reverse_bfs_traces(set(changed_qualified))
        ]