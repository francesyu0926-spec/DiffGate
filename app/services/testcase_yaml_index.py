"""YAML / HttpRunner 声明式用例 → 索引记录（无 PyYAML，正则 + 轻量结构）。"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.db.models import Repository
from app.services.testcase_route_align import align_test_route

_RE_CONFIG_NAME = re.compile(r"^\s*name:\s*['\"]?([^'\"#\n]+)", re.M)
_RE_METHOD = re.compile(r"^\s*method:\s*([A-Za-z]+)\s*$", re.M | re.I)
_RE_URL = re.compile(r"^\s*url:\s*['\"]?([^'\"#\s]+)", re.M)
_RE_PATH = re.compile(r"^\s*path:\s*['\"]?([^'\"#\s]+)", re.M)
_RE_STEP_HEADER = re.compile(r"^\s*-\s*name:\s*['\"]?([^'\"#\n]+)", re.M)


@dataclass
class ParsedBinding:
    http_method: str
    raw_route: str
    normalized_route: str
    contract_key: str
    fingerprint: str


@dataclass
class ParsedCase:
    case_uid: str
    title: str
    run_selector: str
    file_path: str
    source_framework: str = "yaml"
    bindings: list[ParsedBinding] = field(default_factory=list)


def _extract_steps(text: str) -> list[tuple[str, str, str]]:
    """返回 [(step_name, method, url)]。"""
    if "teststeps:" in text:
        chunks = re.split(r"(?m)^\s*-\s+name:", text)
        steps: list[tuple[str, str, str]] = []
        for i, chunk in enumerate(chunks):
            if i == 0:
                continue
            step_name = (chunk.split("\n", 1)[0] or "").strip().strip("'\"")
            m = _RE_METHOD.search(chunk)
            method = (m.group(1) if m else "GET").upper()
            um = _RE_URL.search(chunk) or _RE_PATH.search(chunk)
            if not um:
                continue
            steps.append((step_name or "step", method, um.group(1).strip()))
        if steps:
            return steps

    m_name = _RE_CONFIG_NAME.search(text)
    title = (m_name.group(1).strip() if m_name else "").strip()
    method_m = _RE_METHOD.search(text)
    method = (method_m.group(1) if method_m else "GET").upper()
    url_m = _RE_URL.search(text) or _RE_PATH.search(text)
    if url_m:
        return [(title or "case", method, url_m.group(1).strip())]
    return []


def parse_yaml_file(
    path: Path,
    *,
    suite_slug: str,
    root: Path,
    align_repo: Repository | None,
) -> ParsedCase | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    rel = path.relative_to(root).as_posix()
    steps = _extract_steps(text)
    if not steps:
        return None
    m_name = _RE_CONFIG_NAME.search(text)
    case_title = (m_name.group(1).strip() if m_name else path.stem)
    case_uid = f"{suite_slug}:{rel}::{case_title}"
    bindings: list[ParsedBinding] = []
    for _step_name, method, raw_url in steps:
        norm, ck, fp = align_test_route(raw_url, method, align_repo)
        bindings.append(
            ParsedBinding(
                http_method=method,
                raw_route=raw_url,
                normalized_route=norm,
                contract_key=ck,
                fingerprint=fp,
            )
        )
    if not bindings:
        return None
    return ParsedCase(
        case_uid=case_uid,
        title=case_title,
        run_selector=rel,
        file_path=rel,
        bindings=bindings,
    )


def scan_yaml_tree(
    scan_root: Path,
    *,
    suite_slug: str,
    align_repo: Repository | None,
) -> list[ParsedCase]:
    if not scan_root.is_dir():
        return []
    cases: list[ParsedCase] = []
    for pattern in ("*.yaml", "*.yml"):
        for path in scan_root.rglob(pattern):
            if path.is_file():
                row = parse_yaml_file(path, suite_slug=suite_slug, root=scan_root, align_repo=align_repo)
                if row:
                    cases.append(row)
    return cases