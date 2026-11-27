"""目录树扫描 + 特征文件识别（纯函数 + 本地采集）。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

IGNORED_DIRS = frozenset(
    {
        ".git",
        ".github",
        ".gitlab",
        ".idea",
        ".vscode",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        "venv",
        ".venv",
        "env",
        "dist",
        "build",
        "target",
        "vendor",
        "out",
        ".tox",
        "coverage",
    }
)

TECH_SIGNATURES: dict[str, tuple[str, str, str]] = {
    "pom.xml": ("java", "Java (Maven)", "src/main/java"),
    "build.gradle": ("java", "Java (Gradle)", "src/main/java"),
    "build.gradle.kts": ("java", "Java (Gradle)", "src/main/java"),
    "go.mod": ("go", "Go", "."),
    "requirements.txt": ("python", "Python", "."),
    "pyproject.toml": ("python", "Python", "."),
    "setup.py": ("python", "Python", "."),
    "Pipfile": ("python", "Python", "."),
}

FRONTEND_DEPS = frozenset({"vue", "react", "next", "nuxt", "@angular/core", "svelte", "vite"})
NODE_BACKEND_DEPS = frozenset({"@nestjs/core", "express", "koa", "fastify", "hono"})

_CONTENT_READ_NAMES = frozenset(TECH_SIGNATURES.keys()) | {"package.json"}

_SHORT_TO_REPO_ID = {
    "python": "backend_python",
    "java": "backend_java",
    "go": "backend_go",
    "frontend": "frontend",
    "nodejs": "backend_node",
}

_REPO_LABEL = {
    "backend_python": "后端 (Python)",
    "backend_java": "后端 (Java)",
    "frontend": "前端 (TS/JS)",
    "backend_node": "后端 (Node.js/TS)",
    "backend_go": "后端 (Go)",
}


def _classify_package_json(pkg_content: str) -> tuple[str, str, str]:
    try:
        data = json.loads(pkg_content)
        deps: dict[str, Any] = {}
        deps.update(data.get("dependencies") or {})
        deps.update(data.get("devDependencies") or {})
        dep_keys = set(deps.keys())

        if dep_keys & FRONTEND_DEPS:
            framework = next((k for k in ("vue", "react", "next", "nuxt") if k in dep_keys), "Frontend")
            return ("frontend", f"前端 ({framework.capitalize()})", "src")
        if dep_keys & NODE_BACKEND_DEPS:
            framework = next((k for k in ("@nestjs/core", "express", "koa", "fastify") if k in dep_keys), "Node.js")
            return ("nodejs", f"Node.js ({framework})", "src")
    except Exception:
        pass
    return ("frontend", "TS/JS 项目", "src")


def _path_blocked(parts: list[str]) -> bool:
    return any(part in IGNORED_DIRS or (part.startswith(".") and part not in {".", ".."}) for part in parts)


def analyze_directory_tree(
    all_files: list[str],
    file_contents: dict[str, str],
    *,
    max_depth: int = 3,
) -> dict[str, Any]:
    """根据文件路径列表 + 关键配置内容，生成 directories / candidates / recommended_root。"""
    valid_dirs: set[str] = {"."}
    dir_files: dict[str, list[str]] = {".": []}

    for raw_path in all_files:
        norm = raw_path.strip().replace("\\", "/").lstrip("./")
        if not norm:
            continue
        parts = norm.split("/")
        if _path_blocked(parts):
            continue
        if len(parts) > 1 and _path_blocked(parts[:-1]):
            continue

        if parts[-1] == ".keep":
            tree_path = "/".join(parts[:-1]) if len(parts) > 1 else "."
            valid_dirs.add(tree_path if tree_path else ".")
            continue

        parent_dir = "/".join(parts[:-1]) if len(parts) > 1 else "."
        fname = parts[-1]

        dir_files.setdefault(parent_dir, []).append(fname)

        for depth in range(1, min(len(parts), max_depth + 1)):
            sub_dir = "/".join(parts[:depth])
            valid_dirs.add(sub_dir)
            dir_files.setdefault(sub_dir, [])

    candidates: list[dict[str, Any]] = []
    dir_meta: dict[str, dict[str, Any]] = {}

    for d in sorted(valid_dirs):
        files_in_d = dir_files.get(d, [])
        matched_type: str | None = None
        framework_label: str | None = None
        recommended_subpath: str | None = None
        matched_sig_files: list[str] = []

        for sig_file, (lang_type, label, default_sub) in TECH_SIGNATURES.items():
            if sig_file in files_in_d:
                matched_type = lang_type
                framework_label = label
                matched_sig_files.append(sig_file)
                if default_sub == ".":
                    recommended_subpath = d
                else:
                    candidate_sub = f"{d}/{default_sub}" if d != "." else default_sub
                    recommended_subpath = candidate_sub if candidate_sub in valid_dirs else d
                break

        if not matched_type and "package.json" in files_in_d:
            pkg_full_path = f"{d}/package.json" if d != "." else "package.json"
            pkg_text = file_contents.get(pkg_full_path, "")
            matched_type, framework_label, default_sub = _classify_package_json(pkg_text)
            matched_sig_files.append("package.json")
            candidate_sub = f"{d}/{default_sub}" if d != "." else default_sub
            recommended_subpath = candidate_sub if candidate_sub in valid_dirs else d

        if matched_type and recommended_subpath:
            if not any(c["scan_root"] == recommended_subpath and c["repo_type"] == matched_type for c in candidates):
                candidates.append(
                    {
                        "repo_type": matched_type,
                        "label": framework_label,
                        "scan_root": recommended_subpath,
                        "framework": framework_label,
                    }
                )

        if matched_sig_files:
            summary = f"{framework_label} · 含 {', '.join(matched_sig_files)}"
        elif files_in_d:
            sample = ", ".join(sorted(files_in_d)[:3])
            summary = f"含 {sample}" + (" 等" if len(files_in_d) > 3 else "")
        else:
            summary = "子目录"

        dir_meta[d] = {
            "path": d,
            "label": ".（仓库根目录）" if d == "." else d,
            "is_recommended": False,
            "matched_type": matched_type,
            "file_summary": summary,
        }

    recommended_roots = {c["scan_root"]: c["repo_type"] for c in candidates}
    for r_path, r_type in recommended_roots.items():
        if r_path in dir_meta:
            dir_meta[r_path]["is_recommended"] = True
            if not dir_meta[r_path]["matched_type"]:
                dir_meta[r_path]["matched_type"] = r_type

    if not candidates:
        if "." in dir_meta:
            dir_meta["."]["is_recommended"] = True
        detected_type = "python"
        recommended_root = "."
    else:
        primary = next((c for c in candidates if c["repo_type"] != "frontend"), candidates[0])
        detected_type = primary["repo_type"]
        recommended_root = primary["scan_root"]

    sorted_directories = sorted(
        dir_meta.values(),
        key=lambda item: (0 if item["is_recommended"] else 1, item["path"] != ".", item["path"]),
    )

    repo_types_found = {c["repo_type"] for c in candidates}
    is_monorepo = len(candidates) >= 2 and "frontend" in repo_types_found and len(repo_types_found) >= 2

    return {
        "is_monorepo": is_monorepo,
        "detected_type": detected_type,
        "recommended_root": recommended_root,
        "candidates": candidates,
        "directories": sorted_directories,
    }


def _should_read_content(fname: str) -> bool:
    return fname in _CONTENT_READ_NAMES


def collect_repo_file_index(
    root: Path,
    *,
    walk_max_depth: int = 4,
) -> tuple[list[str], dict[str, str]]:
    root = root.expanduser().resolve()
    all_files: list[str] = []
    file_contents: dict[str, str] = {}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
        rel_dir = Path(dirpath).relative_to(root)
        if len(rel_dir.parts) > walk_max_depth:
            dirnames[:] = []
            continue

        for fname in filenames:
            if fname.startswith("."):
                continue
            rel_file = (rel_dir / fname).as_posix() if str(rel_dir) != "." else fname
            all_files.append(rel_file)
            if _should_read_content(fname):
                try:
                    file_contents[rel_file] = (Path(dirpath) / fname).read_text(encoding="utf-8", errors="replace")[
                        :10_000
                    ]
                except OSError:
                    pass

    return all_files, file_contents


def paths_set_to_all_files(paths: set[str]) -> list[str]:
    """将探测 path 集合转为分析器可用的相对文件路径列表。"""
    out: list[str] = []
    for raw in sorted(paths):
        norm = raw.strip().replace("\\", "/").lstrip("./")
        if not norm or norm == ".":
            continue
        name = norm.split("/")[-1]
        if "." in name or name in _CONTENT_READ_NAMES:
            out.append(norm)
        elif "/" not in norm:
            out.append(f"{norm}/.keep")
    return out


def enrich_contents_from_paths(paths: set[str], contents: dict[str, str]) -> dict[str, str]:
    merged = dict(contents)
    for p in paths:
        norm = p.replace("\\", "/").lstrip("./")
        base = norm.split("/")[-1]
        if base in _CONTENT_READ_NAMES and norm in contents and norm not in merged:
            merged[norm] = contents[norm]
    return merged


def run_directory_analysis(
    *,
    paths: set[str] | None = None,
    contents: dict[str, str] | None = None,
    repo_dir: Path | None = None,
    max_depth: int = 3,
) -> dict[str, Any]:
    if repo_dir is not None and repo_dir.is_dir():
        all_files, file_contents = collect_repo_file_index(repo_dir)
    elif paths:
        all_files = paths_set_to_all_files(paths)
        file_contents = enrich_contents_from_paths(paths, contents or {})
    else:
        all_files, file_contents = [], {}

    return analyze_directory_tree(all_files, file_contents, max_depth=max_depth)


def analyzed_candidates_for_api(analyzed: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for c in analyzed.get("candidates") or []:
        short = c.get("repo_type") or "python"
        rid = _SHORT_TO_REPO_ID.get(short, "backend_python")
        items.append(
            {
                "repo_type": short,
                "repo_type_id": rid,
                "label": _REPO_LABEL.get(rid, c.get("label") or short),
                "scan_root": c.get("scan_root") or ".",
                "framework": c.get("framework"),
            }
        )
    return items


def repo_id_from_detected_type(detected_type: str | None) -> str:
    return _SHORT_TO_REPO_ID.get((detected_type or "").lower(), "backend_python")