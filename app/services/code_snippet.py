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


def _read_head_file(repo_dir: Path, head_sha: str, file_path: str) -> list[str]:
    proc = subprocess.run(
        ["git", "show", f"{head_sha}:{file_path}"],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode == 0 and proc.stdout:
        return proc.stdout.splitlines()
    worktree = repo_dir / file_path
    if worktree.is_file():
        return worktree.read_text(encoding="utf-8", errors="replace").splitlines()
    return []


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
) -> tuple[list[dict], list[int]]:
    all_lines = _read_head_file(repo_dir, head_sha, file_path)
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
) -> dict:
    repo_dir = _repo_dir(repo_full_name, clone_root)
    if not repo_dir.is_dir():
        raise FileNotFoundError("分析工作区不存在，请重新运行分析任务")

    file_path = file_path.replace("\\", "/").lstrip("/")

    all_file = _read_head_file(repo_dir, head_sha, file_path)
    if node_type == "api":
        start_line, end_line = _expand_range(all_file, start_line, end_line, min_span=56)
    elif node_type == "symbol":
        start_line, end_line = _expand_range(all_file, start_line, end_line, min_span=32)

    if node_type == "changed":
        raw = _git_diff_raw(repo_dir, base_sha, head_sha, file_path)
        lines = _parse_diff_hunks(raw, start_line, end_line) if raw.strip() else []
        if not lines:
            lines, _ = _source_snippet(repo_dir, head_sha, file_path, start_line, end_line)
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
        }

    lines, highlight = _source_snippet(
        repo_dir,
        head_sha,
        file_path,
        start_line,
        end_line,
        highlight_qnames=highlight_qnames,
    )
    hint = None
    if node_type in ("api", "symbol") and highlight:
        hint = "↓ 高亮行为对下游变更函数的调用"
    elif node_type in ("api", "symbol") and not lines and all_file:
        start_line, end_line = 1, min(len(all_file), 120)
        lines, highlight = _source_snippet(
            repo_dir,
            head_sha,
            file_path,
            start_line,
            end_line,
            highlight_qnames=highlight_qnames,
        )
        hint = "已回退展示文件前段源码（原行号区间不可用）"

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
    }