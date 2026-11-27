"""仓库指纹：基于路径集合与小文件内容识别类型与 Monorepo 候选。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.adapters.registry import list_repo_type_options

_REPO_LABEL = {r["id"]: r["label"] for r in list_repo_type_options()}

_DETECTED_TYPE = {
    "backend_python": "python",
    "backend_java": "java",
    "backend_go": "go",
    "frontend": "frontend",
    "backend_node": "nodejs",
}

_MONOREPO_DIRS = ("backend", "server", "frontend", "web")
_JAVA_MARKERS = ("pom.xml", "build.gradle", "build.gradle.kts")
_PY_MARKERS = ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile")


def _norm_path(p: str) -> str:
    s = p.replace("\\", "/").strip().removeprefix("./")
    return s if s else "."


def _label(repo_type: str) -> str:
    return _REPO_LABEL.get(repo_type, repo_type)


def _read_json(blob: str) -> dict:
    try:
        return json.loads(blob)
    except Exception:
        return {}


def _package_json_signals(blob: str) -> tuple[bool, bool, str | None]:
    data = _read_json(blob)
    deps = json.dumps({**data.get("dependencies", {}), **data.get("devDependencies", {})}, ensure_ascii=False).lower()
    fe = any(k in deps for k in ("vue", "react", "vite", "next", "nuxt", "@angular/core"))
    be = any(k in deps for k in ("@nestjs/core", "express", "koa", "fastify", "hapi"))
    framework: str | None = None
    if "vue" in deps:
        framework = "Vue 3" if "3" in deps else "Vue"
    elif "react" in deps:
        framework = "React"
    elif "next" in deps:
        framework = "Next.js"
    elif "@nestjs/core" in deps:
        framework = "NestJS"
    elif "express" in deps:
        framework = "Express"
    return fe, be, framework


def _py_framework(blob: str, path: str) -> str | None:
    low = blob.lower()
    if "fastapi" in low:
        return "FastAPI"
    if "django" in low:
        return "Django"
    if "flask" in low:
        return "Flask"
    if path.endswith("pyproject.toml") and "fastapi" in low:
        return "FastAPI"
    return None


@dataclass
class DetectCandidate:
    repo_type: str
    scan_root: str
    label: str
    framework: str | None = None

    def to_dict(self) -> dict:
        return {
            "repo_type": _DETECTED_TYPE.get(self.repo_type, self.repo_type),
            "repo_type_id": self.repo_type,
            "label": self.label,
            "scan_root": self.scan_root,
            "framework": self.framework,
        }


@dataclass
class FingerprintResult:
    repo_type: str
    scan_root: str
    confidence: str = "medium"
    is_monorepo: bool = False
    candidates: list[DetectCandidate] = field(default_factory=list)
    framework: str | None = None

    @property
    def detected_type(self) -> str:
        return _DETECTED_TYPE.get(self.repo_type, self.repo_type)

    @property
    def label(self) -> str:
        return _label(self.repo_type)


def _has_path(paths: set[str], rel: str) -> bool:
    rel = _norm_path(rel)
    if rel in paths:
        return True
    if rel.endswith("/"):
        prefix = rel.rstrip("/") + "/"
        return any(p.startswith(prefix) for p in paths)
    return False


def _file_text(paths: set[str], contents: dict[str, str], rel: str) -> str | None:
    rel = _norm_path(rel)
    if rel in contents:
        return contents[rel]
    for p, text in contents.items():
        if _norm_path(p) == rel:
            return text
    return None


def _classify_prefix(paths: set[str], contents: dict[str, str], prefix: str) -> DetectCandidate | None:
    pref = _norm_path(prefix)
    check = lambda name: _has_path(paths, f"{pref}/{name}" if pref != "." else name)

    if check("go.mod"):
        return DetectCandidate("backend_go", pref if pref != "." else ".", _label("backend_go"))
    if any(check(n) for n in _JAVA_MARKERS):
        if pref == ".":
            scan = "src/main/java" if _has_path(paths, "src") else "."
        else:
            scan = f"{pref}/src/main/java"
        return DetectCandidate("backend_java", scan, _label("backend_java"))
    if any(check(n) for n in _PY_MARKERS):
        fw = None
        for marker in _PY_MARKERS:
            t = _file_text(paths, contents, f"{pref}/{marker}" if pref != "." else marker)
            if t:
                fw = _py_framework(t, marker)
                break
        scan = pref if pref != "." else "."
        return DetectCandidate("backend_python", scan, _label("backend_python"), fw)
    pkg_rel = f"{pref}/package.json" if pref != "." else "package.json"
    if _has_path(paths, pkg_rel):
        blob = _file_text(paths, contents, pkg_rel) or ""
        fe, be, fw = _package_json_signals(blob)
        if fe:
            scan = f"{pref}/src" if _has_path(paths, f"{pref}/src") else pref
            if pref == ".":
                scan = "src" if _has_path(paths, "src") else "."
            return DetectCandidate("frontend", scan, _label("frontend"), fw)
        if be:
            scan = f"{pref}/src" if _has_path(paths, f"{pref}/src") else pref
            if pref == ".":
                scan = "src" if _has_path(paths, "src") else "."
            return DetectCandidate("backend_node", scan, _label("backend_node"), fw)
    return None


def detect_from_paths(paths: set[str], contents: dict[str, str] | None = None) -> FingerprintResult:
    contents = contents or {}
    norm_paths = {_norm_path(p) for p in paths}

    root_hit = _classify_prefix(norm_paths, contents, ".")
    has_sub_project = any(
        _has_path(norm_paths, f"{sub}/") or any(p.startswith(f"{sub}/") for p in norm_paths)
        for sub in _MONOREPO_DIRS
    )
    if (
        root_hit
        and root_hit.repo_type in ("backend_go", "backend_java", "backend_python", "frontend", "backend_node")
        and not has_sub_project
    ):
        if root_hit.repo_type != "frontend" or not _has_path(norm_paths, "frontend/package.json"):
            return FingerprintResult(
                root_hit.repo_type,
                root_hit.scan_root,
                "high",
                framework=root_hit.framework,
            )

    candidates: list[DetectCandidate] = []
    for sub in _MONOREPO_DIRS:
        if _has_path(norm_paths, f"{sub}/.") or any(p.startswith(f"{sub}/") for p in norm_paths):
            c = _classify_prefix(norm_paths, contents, sub)
            if c:
                candidates.append(c)

    apps_hits = sorted({p.split("/")[0] for p in norm_paths if p.startswith("apps/") and "/" in p})
    for app_root in apps_hits[:6]:
        c = _classify_prefix(norm_paths, contents, app_root)
        if c:
            candidates.append(c)

    ent_uniq: list[DetectCandidate] = []
    seen: set[tuple[str, str]] = set()
    for c in candidates:
        key = (c.repo_type, c.scan_root)
        if key in seen:
            continue
        seen.add(key)
        ent_uniq.append(c)

    fe = [c for c in ent_uniq if c.repo_type == "frontend"]
    be = [c for c in ent_uniq if c.repo_type != "frontend"]

    if fe and be:
        primary = be[0]
        return FingerprintResult(
            primary.repo_type,
            primary.scan_root,
            "high",
            is_monorepo=True,
            candidates=ent_uniq,
            framework=primary.framework,
        )

    if ent_uniq:
        c = ent_uniq[0]
        return FingerprintResult(c.repo_type, c.scan_root, "high", candidates=ent_uniq, framework=c.framework)

    if root_hit:
        return FingerprintResult(root_hit.repo_type, root_hit.scan_root, "medium", framework=root_hit.framework)

    return FingerprintResult("backend_python", ".", "low")


def collect_local_paths(repo_dir: Path, max_depth: int = 3) -> tuple[set[str], dict[str, str]]:
    root = repo_dir.resolve()
    paths: set[str] = set()
    contents: dict[str, str] = {}
    if (root / ".git").exists() or True:
        paths.add(".")
    for item in root.iterdir():
        if item.name.startswith("."):
            continue
        rel = item.name
        paths.add(rel)
        if item.is_file() and item.stat().st_size <= 120_000:
            name = item.name.lower()
            if name in (
                "package.json",
                "go.mod",
                "pom.xml",
                "build.gradle",
                "build.gradle.kts",
                "requirements.txt",
                "pyproject.toml",
                "setup.py",
                "pipfile",
            ):
                try:
                    contents[rel] = item.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
        elif item.is_dir() and max_depth >= 2:
            for child in item.iterdir():
                if child.name.startswith("."):
                    continue
                rel2 = f"{item.name}/{child.name}"
                paths.add(rel2)
                if child.is_file() and child.stat().st_size <= 120_000:
                    n2 = child.name.lower()
                    if n2 in _JAVA_MARKERS + _PY_MARKERS + ("package.json", "go.mod"):
                        try:
                            contents[rel2] = child.read_text(encoding="utf-8", errors="replace")
                        except OSError:
                            pass
    return paths, contents


def detect_from_directory(repo_dir: Path) -> FingerprintResult:
    paths, contents = collect_local_paths(repo_dir)
    return detect_from_paths(paths, contents)


def suggest_project_name(clone_url: str) -> str | None:
    from app.services.repo_detect_parse import parse_clone_url_meta

    meta = parse_clone_url_meta(clone_url)
    return meta.repo_name if meta else None