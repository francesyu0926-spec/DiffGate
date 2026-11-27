"""Java 增量覆盖率分母清洗（配合 JaCoCo / git diff）。"""

from __future__ import annotations

import re

_LOMBOK = re.compile(r"^\s*@(?:Data|Getter|Setter|Builder|Value|Slf4j)\b")
_FIELD_ONLY = re.compile(
    r"^\s*(?:private|protected|public)\s+(?:static\s+)?(?:final\s+)?[\w<>,\[\]\s]+\s+\w+\s*;\s*$"
)


def is_java_test_path(path: str) -> bool:
    norm = path.replace("\\", "/").lower()
    return "/src/test/java/" in norm or norm.startswith("src/test/java/")


def is_java_executable_line(line: str) -> bool:
    raw = line.rstrip("\n\r")
    stripped = raw.strip()
    if not stripped:
        return False
    if stripped.startswith("//"):
        return False
    if stripped.startswith("/*") or stripped.startswith("*") or stripped.endswith("*/"):
        return False
    if stripped.startswith("package ") or stripped.startswith("import "):
        return False
    if _LOMBOK.match(stripped):
        return False
    if _FIELD_ONLY.match(stripped):
        return False
    return True