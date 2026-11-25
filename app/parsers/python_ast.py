import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SymbolDef:
    qualified_name: str
    file_path: str
    kind: str  # function | method | class
    start_line: int
    end_line: int
    calls: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    is_api_handler: bool = False
    http_method: str | None = None
    route_path: str | None = None


FASTAPI_DECORATORS = {"get", "post", "put", "patch", "delete", "head", "options", "api_route"}
API_DECORATOR_ROOTS = {"router", "app", "api_router"}
BUILTIN_CALL_NAMES = frozenset(
    {
        "str",
        "int",
        "float",
        "bool",
        "len",
        "range",
        "list",
        "dict",
        "set",
        "tuple",
        "print",
        "max",
        "min",
        "enumerate",
        "isinstance",
        "getattr",
        "setattr",
        "hasattr",
        "type",
        "super",
        "open",
        "any",
        "all",
        "sorted",
        "zip",
        "map",
        "filter",
        "abs",
        "round",
        "repr",
        "format",
    }
)


def _qualify(module_path: str, stack: list[str], name: str) -> str:
    parts = [module_path.replace("/", ".").removesuffix(".py")]
    parts.extend(stack)
    parts.append(name)
    return ".".join(p for p in parts if p)


def _relative_import_module(module_path: str, level: int, module: str | None) -> str:
    if level == 0:
        return (module or "").replace("/", ".")
    parts = module_path.split(".")
    trim = min(level, len(parts))
    parts = parts[:-trim] if trim else []
    if module:
        parts.extend(module.split("."))
    return ".".join(p for p in parts if p)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        if base:
            return f"{base}.{node.attr}"
        return node.attr
    return None


def _route_from_decorator(dec: ast.Call) -> tuple[str | None, str | None]:
    method = dec.func.attr if isinstance(dec.func, ast.Attribute) else None
    route = None
    if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
        route = dec.args[0].value
    return method, route


def _name_id(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return None


@dataclass
class ResolveContext:
    module_path: str
    stack: list[str]
    imports: dict[str, str]
    module_bindings: dict[str, str]
    class_names: set[str]

    @property
    def class_qname(self) -> str | None:
        for name in reversed(self.stack):
            if name in self.class_names:
                parts = [self.module_path, *self.stack[: self.stack.index(name) + 1]]
                return ".".join(parts)
        return None

    def import_stub(self, name: str) -> str | None:
        return self.imports.get(name)

    def resolve_ctor_name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Call):
            return self.resolve_type_name(node.func)
        return self.resolve_type_name(node)

    def resolve_type_name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            stub = self.import_stub(node.id)
            if stub:
                return stub
            if node.id in self.class_names:
                return _qualify(self.module_path, self.stack, node.id)
            return None
        if isinstance(node, ast.Attribute):
            raw = _call_name(node)
            if not raw:
                return None
            head, _, tail = raw.partition(".")
            base = self.import_stub(head) or head
            return f"{base}.{tail}" if tail else base
        return None


def _resolve_call(raw: str, ctx: ResolveContext, locals_map: dict[str, str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(*candidates: str) -> None:
        for c in candidates:
            if not c or c in seen:
                continue
            seen.add(c)
            out.append(c)

    add(raw)

    if raw.startswith("self."):
        method = raw.split(".", 1)[1]
        cq = ctx.class_qname
        if cq:
            add(f"{cq}.{method}")
        add(method)
        return out

    if raw == "self":
        return out

    parts = raw.split(".")
    if len(parts) == 1:
        bare = parts[0]
        stub = ctx.import_stub(bare)
        if stub:
            add(stub)
        return out

    if len(parts) == 2:
        base, attr = parts
        bound = locals_map.get(base) or ctx.module_bindings.get(base)
        if bound:
            add(f"{bound}.{attr}")
        stub = ctx.import_stub(base)
        if stub:
            add(f"{stub}.{attr}")
        if base in ctx.class_names:
            add(f"{_qualify(ctx.module_path, ctx.stack, base)}.{attr}")
        short_class = bound.split(".")[-1] if bound else base
        add(f"{short_class}.{attr}")
        return out

    if len(parts) >= 3:
        head = parts[0]
        tail = ".".join(parts[1:])
        stub = ctx.import_stub(head)
        if stub:
            add(f"{stub}.{tail}")
        bound = locals_map.get(head) or ctx.module_bindings.get(head)
        if bound:
            add(f"{bound}.{tail}")

    return out


def _iter_call_sites(fn: ast.FunctionDef | ast.AsyncFunctionDef):
    for stmt in fn.body:
        for child in ast.walk(stmt):
            if isinstance(child, ast.Await) and isinstance(child.value, ast.Call):
                yield child.value
            elif isinstance(child, ast.Call):
                yield child


def _collect_local_bindings(fn: ast.FunctionDef | ast.AsyncFunctionDef, ctx: ResolveContext) -> dict[str, str]:
    locals_map: dict[str, str] = {}
    for stmt in fn.body:
        for child in ast.walk(stmt):
            if isinstance(child, ast.Assign):
                typ = ctx.resolve_ctor_name(child.value)
                if not typ:
                    continue
                for target in child.targets:
                    name = _name_id(target)
                    if name:
                        locals_map[name] = typ
            elif isinstance(child, ast.AnnAssign) and child.annotation and child.target:
                name = _name_id(child.target)
                if not name:
                    continue
                typ = ctx.resolve_type_name(child.annotation)
                if typ:
                    locals_map[name] = typ
    return locals_map


def _collect_calls(fn: ast.FunctionDef | ast.AsyncFunctionDef, ctx: ResolveContext) -> list[str]:
    locals_map = _collect_local_bindings(fn, ctx)
    calls: list[str] = []
    seen: set[str] = set()
    for call_node in _iter_call_sites(fn):
        raw = _call_name(call_node.func)
        if not raw:
            continue
        head = raw.split(".", 1)[0]
        if head in BUILTIN_CALL_NAMES and head not in ctx.imports:
            continue
        if head in {"asyncio", "logging", "pd", "pandas"}:
            continue
        for target in _resolve_call(raw, ctx, locals_map):
            if target not in seen:
                seen.add(target)
                calls.append(target)
    return calls


class SymbolVisitor(ast.NodeVisitor):
    def __init__(self, module_path: str, rel_path: str):
        self.module_path = module_path
        self.rel_path = rel_path
        self.stack: list[str] = []
        self.symbols: list[SymbolDef] = []
        self.imports: dict[str, str] = {}
        self.module_bindings: dict[str, str] = {}
        self.class_names: set[str] = set()

    @property
    def _ctx(self) -> ResolveContext:
        return ResolveContext(
            module_path=self.module_path,
            stack=list(self.stack),
            imports=self.imports,
            module_bindings=dict(self.module_bindings),
            class_names=set(self.class_names),
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name
            stub = alias.name.replace(".", ".")
            self.imports[name] = stub

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = _relative_import_module(self.module_path, node.level, node.module)
        for alias in node.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            self.imports[local] = f"{base}.{alias.name}"

    def visit_Assign(self, node: ast.Assign) -> None:
        if self.stack:
            self.generic_visit(node)
            return
        typ = self._ctx.resolve_ctor_name(node.value)
        if typ:
            for target in node.targets:
                name = _name_id(target)
                if name:
                    self.module_bindings[name] = typ
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_function(node)

    def _handle_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qname = _qualify(self.module_path, self.stack, node.name)
        dec_names: list[str] = []
        is_api = False
        http_method: str | None = None
        route_path: str | None = None
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if isinstance(dec.func.value, ast.Name) and dec.func.value.id in API_DECORATOR_ROOTS:
                    if dec.func.attr in FASTAPI_DECORATORS:
                        is_api = True
                        http_method, route_path = _route_from_decorator(dec)
                dec_names.append(dec.func.attr)
            elif isinstance(dec, ast.Name):
                dec_names.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                dec_names.append(dec.attr)

        calls = _collect_calls(node, self._ctx)

        end_line = getattr(node, "end_lineno", node.lineno)
        in_class = any(name in self.class_names for name in self.stack)
        self.symbols.append(
            SymbolDef(
                qualified_name=qname,
                file_path=self.rel_path,
                kind="method" if in_class else "function",
                start_line=node.lineno,
                end_line=end_line or node.lineno,
                calls=calls,
                decorators=dec_names,
                is_api_handler=is_api,
                http_method=http_method,
                route_path=route_path,
            )
        )

        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qname = _qualify(self.module_path, self.stack, node.name)
        self.class_names.add(node.name)
        end_line = getattr(node, "end_lineno", node.lineno)
        self.symbols.append(
            SymbolDef(
                qualified_name=qname,
                file_path=self.rel_path,
                kind="class",
                start_line=node.lineno,
                end_line=end_line or node.lineno,
            )
        )
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()
        self.class_names.discard(node.name)


def parse_python_file(repo_root: Path, rel_path: str) -> list[SymbolDef]:
    full = repo_root / rel_path
    if not full.is_file():
        return []
    source = full.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(full))
    except SyntaxError:
        return []

    module_path = rel_path.replace("\\", "/")
    if module_path.endswith(".py"):
        module_path = module_path[:-3]
    visitor = SymbolVisitor(module_path, rel_path.replace("\\", "/"))
    visitor.visit(tree)
    return visitor.symbols


def scan_python_repo(repo_root: Path, scan_root: str = ".") -> list[SymbolDef]:
    symbols: list[SymbolDef] = []
    repo_root = repo_root.resolve()
    scan_root = (scan_root or ".").strip().lstrip("/")
    base = (repo_root / scan_root).resolve() if scan_root not in (".", "") else repo_root
    if not base.is_dir() or not str(base).startswith(str(repo_root)):
        base = repo_root
    for path in base.rglob("*.py"):
        try:
            rel_parts = path.resolve().relative_to(repo_root).parts
        except ValueError:
            continue
        if any(
            part in rel_parts
            for part in (".git", "venv", ".venv", "node_modules", "tests", "test", "__pycache__")
        ):
            continue
        rel = str(path.resolve().relative_to(repo_root)).replace("\\", "/")
        symbols.extend(parse_python_file(repo_root, rel))
    return symbols