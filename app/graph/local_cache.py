import json
from pathlib import Path

from app.config import get_settings


def _base() -> Path:
    root = Path(get_settings().local_data_dir) / "cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_json(rel_path: str, payload: dict) -> None:
    path = _base() / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def read_json(rel_path: str) -> dict | None:
    path = _base() / rel_path
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))