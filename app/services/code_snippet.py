"""按任务 commit 范围抽取单文件/函数级 diff 或源码片段。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _repo_dir(repo_full_name: str, clone_root: str) -> Path:
    safe = repo_full_name.replace("/", "_")
    return (Path(clone_root) / safe).resolve()


def _git_diff_raw(repo_dir: Path, base_sha: str, head_sha: str, file_path: str) -> str:
    proc = subprocess.run(
        ["git", "diff", "-U3", base_sha, head_sha, "--", file_path],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return proc.stdout or proc.stderr or ""
    return proc.stdout


def _file_path_candidates(
    repo_dir: Path,
    file_path: str,
    *,
    scan_root: str = ".",
) -> list[str]:
    fp = file_path.replace("\\", "/").lstrip("/")
    seen: set[str] = set()
    candidates: list[str] = []

    def add(path: str) -> None:
        norm = path.replace("\\", "/").lstrip("/")
        if norm and norm not in seen:
            seen.add(norm)
            candidates.append(norm)

    add(fp)
    scan = (scan_root or ".").strip().strip("/").replace("\\", "/")
    if scan and scan not in (".", ""):
        if fp.startswith(f"{scan}/"):
            add(fp[len(scan) + 1 :])
        else:
            add(f"{scan}/{fp}")
    parts = fp.split("/")
    if len(parts) > 1:
        add("/".join(parts[1:]))
    if len(parts) > 2:
        add("/".join(parts[2:]))
    for prefix in ("backend/", "src/", "app/", "lib/"):
        if not fp.startswith(prefix):
            add(f"{prefix}{fp}")
    if (repo_dir / fp).is_file():
        return candidates
    return candidates


def _read_head_file(
    repo_dir: Path,
    head_sha: str,
    file_path: str,
    *,
    scan_root: str = ".",
) -> tuple[list[str], str | None]:
    for candidate in _file_path_candidates(repo_dir, file_path, scan_root=scan_root):
        for ref in (head_sha, "HEAD"):
            if not ref:
                continue
            proc = subprocess.run(
                ["git", "show", f"{ref}:{candidate}"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout.splitlines(), candidate
        worktree = repo_dir / candidate
        if worktree.is_file():
            return worktree.read_text(encoding="utf-8", errors="replace").splitlines(), candidate
    return [], None


_TOP_LEVEL_BOUNDARY = re.compile(r"^(async\s+def|def|class)\b|^[a-zA-Z_].*:\s*$|^@")


def _is_top_level_boundary(line: str) -> bool:
    if not line or line[:1] in (" ", "\t"):
        return False
    stripped = line.lstrip()
    if not stripped or stripped.startswith("#"):
        return False
    if stripped.startswith("@"):
        return True
    if stripped.startswith("@app."):
        return True
    return bool(_TOP_LEVEL_BOUNDARY.match(stripped))


def _include_leading_decorators(all_lines: list[str], start_line: int) -> int:
    idx = max(0, start_line - 1)
    while idx > 0 and all_lines[idx - 1].lstrip().startswith("@"):
        if all_lines[idx - 1][:1] in (" ", "\t"):
            break
        idx -= 1
    return idx + 1


def _clamp_source_end(all_lines: list[str], start_line: int, end_line: int) -> int:
    """在下一顶级 def/class/装饰器前截断，避免把后续路由函数带进来。"""
    start_idx = max(0, start_line - 1)
    anchor_idx = start_idx
    if start_idx < len(all_lines) and all_lines[start_idx].lstrip().startswith("@"):
        for j in range(start_idx + 1, min(len(all_lines), start_idx + 8)):
            stripped = all_lines[j].lstrip()
            if stripped.startswith("def ") or stripped.startswith("async def "):
                anchor_idx = j
                break
    scan_to = min(len(all_lines), max(end_line, start_line) + 400)
    for i in range(anchor_idx + 1, scan_to):
        if _is_top_level_boundary(all_lines[i]):
            last = i - 1
            while last > start_idx and not all_lines[last].strip():
                last -= 1
            return max(start_line, last + 1)
    return min(end_line, len(all_lines)) if all_lines else end_line


def _expand_range(
    all_lines: list[str],
    start_line: int,
    end_line: int,
    *,
    min_span: int = 48,
) -> tuple[int, int]:
    start_line = max(1, start_line)
    end_line = max(start_line, end_line)
    if len(all_lines) and end_line - start_line < min_span:
        end_line = min(len(all_lines), start_line + min_span)
    return start_line, end_line


def _parse_diff_hunks(raw: str, start_line: int, end_line: int) -> list[dict]:
    """仅保留与新文件行号 [start_line, end_line] 相交的 diff 行。"""
    lines_out: list[dict] = []
    new_line = 0
    in_hunk = False
    hunk_intersects = False

    for line in raw.splitlines():
        if line.startswith("@@"):
            in_hunk = True
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            new_line = int(m.group(1)) - 1 if m else 0
            hunk_intersects = False
            continue
        if not in_hunk or line.startswith("---") or line.startswith("+++"):
            continue

        kind = "ctx"
        if line.startswith("+") and not line.startswith("+++"):
            kind = "add"
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            kind = "del"
        elif line.startswith(" "):
            kind = "ctx"
            new_line += 1
        else:
            continue

        intersects = False
        if kind in ("add", "ctx"):
            intersects = start_line <= new_line <= end_line
        elif kind == "del":
            intersects = start_line <= max(new_line, 1) <= end_line + 3

        if intersects:
            hunk_intersects = True
            text = line[1:] if line[:1] in "+- " else line
            lines_out.append(
                {
                    "line_no": new_line if kind != "del" else None,
                    "text": text,
                    "kind": kind,
                }
            )
        elif hunk_intersects and kind == "ctx" and lines_out:
            break

    return lines_out


def _source_snippet(
    repo_dir: Path,
    head_sha: str,
    file_path: str,
    start_line: int,
    end_line: int,
    *,
    highlight_qnames: list[str] | None = None,
    scan_root: str = ".",
) -> tuple[list[dict], list[int]]:
    all_lines, _resolved = _read_head_file(repo_dir, head_sha, file_path, scan_root=scan_root)
    if not all_lines:
        return [], []
    start_line = max(1, start_line)
    end_line = min(len(all_lines), max(start_line, end_line))
    snippet: list[dict] = []
    highlight: list[int] = []
    shorts = {q.split(".")[-1] for q in (highlight_qnames or []) if q}

    for ln in range(start_line, end_line + 1):
        text = all_lines[ln - 1]
        snippet.append({"line_no": ln, "text": text, "kind": "ctx"})
        if shorts:
            for short in shorts:
                if short and short in text and ("(" in text or "." in text):
                    highlight.append(ln)
                    break
    return snippet, sorted(set(highlight))


def _empty_reason(*, repo_exists: bool, file_resolved: bool, line_count: int) -> str | None:
    if line_count > 0:
        return None
    if not repo_exists:
        return "workspace_missing"
    if not file_resolved:
        return "file_not_found"
    return "range_empty"


def job_code_view(
    *,
    repo_full_name: str,
    clone_root: str,
    base_sha: str,
    head_sha: str,
    file_path: str,
    start_line: int,
    end_line: int,
    node_type: str,
    highlight_qnames: list[str] | None = None,
    scan_root: str = ".",
) -> dict:
    repo_dir = _repo_dir(repo_full_name, clone_root)
    if not repo_dir.is_dir():
        raise FileNotFoundError("分析工作区不存在，请对该仓库重新执行一次分析以拉取源码")

    file_path = file_path.replace("\\", "/").lstrip("/")

    all_file, resolved_file = _read_head_file(repo_dir, head_sha, file_path, scan_root=scan_root)
    if resolved_file:
        file_path = resolved_file
    if all_file and node_type == "api":
        start_line = _include_leading_decorators(all_file, start_line)
    if node_type == "api":
        start_line, end_line = _expand_range(all_file, start_line, end_line, min_span=8)
        end_line = min(end_line, start_line + 48)
    elif node_type == "symbol":
        start_line, end_line = _expand_range(all_file, start_line, end_line, min_span=32)
    if all_file and node_type in ("api", "symbol"):
        end_line = _clamp_source_end(all_file, start_line, end_line)

    if node_type == "changed":
        raw = _git_diff_raw(repo_dir, base_sha, head_sha, file_path)
        lines = _parse_diff_hunks(raw, start_line, end_line) if raw.strip() else []
        if not lines:
            lines, _ = _source_snippet(
                repo_dir, head_sha, file_path, start_line, end_line, scan_root=scan_root
            )
        return {
            "view": "diff",
            "file": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "lines": lines,
            "highlight_lines": [],
            "hint": None,
            "source_label": None,
            "empty_reason": _empty_reason(
                repo_exists=True,
                file_resolved=bool(resolved_file),
                line_count=len(lines),
            ),
        }

    if node_type == "api":
        raw = _git_diff_raw(repo_dir, base_sha, head_sha, file_path)
        diff_lines = _parse_diff_hunks(raw, start_line, end_line) if raw.strip() else []
        if diff_lines:
            return {
                "view": "diff",
                "file": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "base_sha": base_sha,
                "head_sha": head_sha,
                "lines": diff_lines,
                "highlight_lines": [],
                "hint": "变更 Diff（当前接口落点存在改动）",
                "source_label": None,
                "empty_reason": None,
            }

    lines, highlight = _source_snippet(
        repo_dir,
        head_sha,
        file_path,
        start_line,
        end_line,
        highlight_qnames=highlight_qnames,
        scan_root=scan_root,
    )
    hint = None
    source_label = None
    if node_type == "api":
        source_label = "当前源码（上游波及）"

    if node_type in ("api", "symbol") and highlight:
        hint = "↓ 高亮行为对下游变更函数的调用"
        source_label = None
    elif node_type in ("api", "symbol") and not lines and all_file:
        start_line, end_line = 1, min(len(all_file), 120)
        lines, highlight = _source_snippet(
            repo_dir,
            head_sha,
            file_path,
            start_line,
            end_line,
            highlight_qnames=highlight_qnames,
            scan_root=scan_root,
        )
        hint = "已回退展示文件前段源码（原行号区间不可用）"
        if node_type == "api":
            source_label = "当前源码（上游波及）"
    elif node_type == "api" and lines:
        hint = None

    return {
        "view": "source",
        "file": file_path,
        "start_line": start_line,
        "end_line": end_line,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "lines": lines,
        "highlight_lines": highlight,
        "hint": hint,
        "source_label": source_label,
        "empty_reason": _empty_reason(
            repo_exists=True,
            file_resolved=bool(resolved_file or all_file),
            line_count=len(lines),
        ),
    }