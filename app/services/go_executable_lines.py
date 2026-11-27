"""Go 增量覆盖率分母清洗。"""

from __future__ import annotations

import re

_STRUCT_ONLY = re.compile(r"^\s*type\s+\w+\s+struct\s*\{")
_INTERFACE_ONLY = re.compile(r"^\s*type\s+\w+\s+interface\s*\{")


def is_go_test_or_generated(path: str) -> bool:
    norm = path.replace("\\", "/").lower()
    base = norm.rsplit("/", 1)[-1]
    if base.endswith("_test.go") or base.endswith(".pb.go"):
        return True
    return "/vendor/" in norm


def is_go_executable_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("//"):
        return False
    if stripped.startswith("/*") or stripped.startswith("*") or stripped.endswith("*/"):
        return False
    if stripped.startswith("package ") or stripped.startswith("import "):
        return False
    if _STRUCT_ONLY.match(stripped) or _INTERFACE_ONLY.match(stripped):
        return False
    if stripped == "{" or stripped == "}":
        return False
    return True