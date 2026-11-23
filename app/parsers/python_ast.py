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


def _qualify(module_path: str, stack: list[str], name: str) -> str:
    parts = [module_path.replace("/", ".").removesuffix(".py")]
    parts.extend(stack)
    parts.append(name)
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


class SymbolVisitor(ast.NodeVisitor):
    def __init__(self, module_path: str, rel_path: str):
        self.module_path = module_path
        self.rel_path = rel_path
        self.stack: list[str] = []
        self.symbols: list[SymbolDef] = []

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

        calls: list[str] = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                name = _call_name(child.func)
                if name:
                    calls.append(name)

        end_line = getattr(node, "end_lineno", node.lineno)
        self.symbols.append(
            SymbolDef(
                qualified_name=qname,
                file_path=self.rel_path,
                kind="method" if self.stack else "function",
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