"""路径级渐进式门禁规则。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_PATH_RULES: list[dict[str, Any]] = [
    {"path_prefix": "app/payment/", "threshold": 95, "allow_override": False},
    {"path_prefix": "app/scripts/", "threshold": 50, "allow_override": True},
]


@dataclass
class PathRule:
    path_prefix: str
    threshold: int
    allow_override: bool = True


def normalize_rules(raw: list[dict] | None) -> list[PathRule]:
    items = raw if raw else DEFAULT_PATH_RULES
    out: list[PathRule] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        prefix = str(row.get("path_prefix") or "").replace("\\", "/")
        if not prefix:
            continue
        out.append(
            PathRule(
                path_prefix=prefix,
                threshold=int(row.get("threshold") or 80),
                allow_override=bool(row.get("allow_override", True)),
            )
        )
    out.sort(key=lambda r: len(r.path_prefix), reverse=True)
    return out


def effective_threshold(
    changed_paths: list[str],
    *,
    repo_rules: list[dict] | None,
    default_threshold: int,
) -> tuple[int, PathRule | None]:
    rules = normalize_rules(repo_rules)
    paths = [p.replace("\\", "/") for p in changed_paths if p]
    best: PathRule | None = None
    for path in paths:
        for rule in rules:
            if path.startswith(rule.path_prefix) or f"/{rule.path_prefix}" in f"/{path}":
                if best is None or rule.threshold > best.threshold:
                    best = rule
                break
    if best:
        return best.threshold, best
    return default_threshold, None


def override_allowed_for_job(
    changed_paths: list[str],
    repo_rules: list[dict] | None,
) -> bool:
    rules = normalize_rules(repo_rules)
    paths = [p.replace("\\", "/") for p in changed_paths if p]
    for path in paths:
        for rule in rules:
            if path.startswith(rule.path_prefix):
                if not rule.allow_override:
                    return False
                break
    return True