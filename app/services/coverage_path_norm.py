"""探针 / coverage 路径与仓库 scan_root 相对路径对齐。"""

from __future__ import annotations

from pathlib import Path


def norm_slashes(path: str) -> str:
    return path.replace("\\", "/").strip()


def strip_leading_relative(path: str) -> str:
    p = norm_slashes(path).lstrip("./")
    while p.startswith("../"):
        p = p[3:]
    return p


_CONTAINER_ROOT_MARKERS = (
    "/app/",
    "/workspace/",
    "/build/",
    "/home/runner/work/",
    "/opt/project/",
    "/src/",
)


def strip_container_prefix(absolute_path: str) -> str:
    p = norm_slashes(absolute_path)
    if not p.startswith("/"):
        return strip_leading_relative(p)
    lowered = p.lower()
    for marker in _CONTAINER_ROOT_MARKERS:
        idx = lowered.find(marker)
        if idx >= 0:
            return strip_leading_relative(p[idx + len(marker) :])
    # 去掉首个绝对段，保留余下路径
    parts = p.split("/")
    if len(parts) > 2:
        return strip_leading_relative("/".join(parts[2:]))
    return strip_leading_relative(p.lstrip("/"))


def align_with_scan_root(rel: str, scan_root: str) -> str:
    rel = strip_leading_relative(rel)
    root = (scan_root or ".").strip().rstrip("/")
    if root in ("", "."):
        return rel
    if rel == root or rel.startswith(f"{root}/"):
        return rel
    return rel


def match_repo_relative_path(
    raw: str,
    candidates: set[str],
    *,
    scan_root: str = ".",
) -> str:
    """
    将探针报告的 file 路径（可能为容器绝对路径）对齐为与 Diff 一致的仓库相对路径。
    """
    if not raw:
        return raw
    norm = norm_slashes(raw)
    if candidates:
        for c in sorted(candidates, key=len, reverse=True):
            c_norm = strip_leading_relative(c)
            if norm == c_norm or norm.endswith(f"/{c_norm}"):
                return align_with_scan_root(c_norm, scan_root)
            idx = norm.find(c_norm)
            if idx >= 0:
                return align_with_scan_root(c_norm, scan_root)
    if norm.startswith("/") or (len(norm) > 1 and norm[1] == ":"):
        stripped = strip_container_prefix(norm)
        if stripped in candidates:
            return align_with_scan_root(stripped, scan_root)
        trial = align_with_scan_root(stripped, scan_root)
        if trial in candidates:
            return trial
        return trial
    rel = align_with_scan_root(strip_leading_relative(norm), scan_root)
    if rel in candidates:
        return rel
    root = (scan_root or ".").strip().rstrip("/")
    if root and root not in ("", "."):
        prefixed = align_with_scan_root(f"{root}/{rel}".replace("//", "/"), scan_root)
        if prefixed in candidates:
            return prefixed
    return rel


def normalize_probe_dicts(
    probes: list[dict],
    *,
    scan_root: str = ".",
    candidate_paths: set[str] | None = None,
) -> list[dict]:
    if not probes:
        return []
    candidates = set(candidate_paths or ())
    out: list[dict] = []
    for row in probes:
        item = dict(row)
        f = item.get("file")
        if isinstance(f, str) and f:
            item["file"] = match_repo_relative_path(f, candidates, scan_root=scan_root)
        out.append(item)
    return out


def repo_path_from_coverage_abs(
    abs_path: str,
    repo_dir: Path,
    workdir: Path,
) -> str | None:
    """与 coverage_probe._lines_executed 一致的路径映射，并额外剥离容器前缀。"""
    try:
        rel = Path(abs_path).resolve().relative_to(repo_dir.resolve())
        return strip_leading_relative(rel.as_posix())
    except ValueError:
        try:
            rel = Path(abs_path).resolve().relative_to(workdir.resolve())
            prefix = workdir.resolve().relative_to(repo_dir.resolve()).as_posix()
            combined = f"{prefix}/{rel.as_posix()}".lstrip("./")
            return strip_leading_relative(combined)
        except ValueError:
            stripped = strip_container_prefix(abs_path)
            if stripped and not stripped.startswith("/"):
                return align_with_scan_root(stripped, ".")
            return None