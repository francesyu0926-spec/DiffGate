"""清空已接入仓库、分析任务及相关缓存（保留登录用户与会话）。

用法（项目根目录）:
  python scripts/reset_platform_data.py
  python scripts/reset_platform_data.py --yes
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def _load_paths() -> tuple[Path, Path, bool, str]:
    """Resolve paths from app config when available, else .env + defaults."""
    try:
        from app.config import get_settings

        s = get_settings()
        return (
            Path(s.local_data_dir).resolve(),
            Path(s.repo_clone_root).resolve(),
            s.use_redis,
            s.redis_url,
        )
    except Exception:
        env = ROOT / ".env"
        vals: dict[str, str] = {}
        if env.is_file():
            for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
        local = Path(vals.get("LOCAL_DATA_DIR", "./data"))
        if not local.is_absolute():
            local = (ROOT / local).resolve()
        clone = Path(vals.get("REPO_CLONE_ROOT", "./data/repos"))
        if not clone.is_absolute():
            clone = (ROOT / clone).resolve()
        use_redis = vals.get("USE_REDIS", "false").lower() in ("1", "true", "yes")
        redis_url = vals.get("REDIS_URL", "redis://localhost:6379/0")
        return local, clone, use_redis, redis_url


def _clear_sqlite_tables() -> dict[str, int]:
    import sqlite3

    env = ROOT / ".env"
    dsn = "sqlite:///data/diffgate.db"
    if env.is_file():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("MYSQL_DSN="):
                dsn = line.split("=", 1)[1].strip()
                break
    if not dsn.startswith("sqlite:"):
        from app.db.models import AnalysisJob, Repository, UserRepoGrant
        from app.db.session import SessionLocal, init_db
        from sqlalchemy import delete, func, select

        init_db()
        db = SessionLocal()
        try:
            jobs_n = db.scalar(select(func.count()).select_from(AnalysisJob)) or 0
            repos_n = db.scalar(select(func.count()).select_from(Repository)) or 0
            grants_n = db.scalar(select(func.count()).select_from(UserRepoGrant)) or 0
            db.execute(delete(AnalysisJob))
            db.execute(delete(UserRepoGrant))
            db.execute(delete(Repository))
            db.commit()
            return {
                "analysis_jobs_deleted": int(jobs_n),
                "repositories_deleted": int(repos_n),
                "user_repo_grants_deleted": int(grants_n),
            }
        finally:
            db.close()

    db_path = dsn.replace("sqlite:///", "")
    if not Path(db_path).is_absolute():
        db_path = str((ROOT / db_path).resolve())
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    stats: dict[str, int] = {}
    for table, key in (
        ("analysis_jobs", "analysis_jobs_deleted"),
        ("user_repo_grants", "user_repo_grants_deleted"),
        ("repositories", "repositories_deleted"),
    ):
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        stats[key] = int(cur.fetchone()[0])
        cur.execute(f"DELETE FROM {table}")
    con.commit()
    con.close()
    return stats


def _clear_redis_job_cache(use_redis: bool, redis_url: str) -> int:
    if not use_redis:
        return 0
    try:
        import redis

        client = redis.from_url(redis_url, decode_responses=True)
        n = 0
        for prefix in ("job:", "cg:"):
            for key in client.scan_iter(f"{prefix}*"):
                client.delete(key)
                n += 1
        return n
    except Exception as exc:
        print(f"  [warn] Redis 清理跳过: {exc}")
        return 0


def _rm_tree(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_file():
        path.unlink()
        return True
    shutil.rmtree(path, ignore_errors=True)
    return True


def _clear_directory_children(path: Path) -> int:
    if not path.is_dir():
        path.mkdir(parents=True, exist_ok=True)
        return 0
    n = 0
    for child in path.iterdir():
        if _rm_tree(child):
            n += 1
    return n


def reset_platform_data() -> dict:
    local_data, clone_root, use_redis, redis_url = _load_paths()
    stats = _clear_sqlite_tables()
    stats["redis_keys_deleted"] = _clear_redis_job_cache(use_redis, redis_url)
    stats["cache_entries_removed"] = _clear_directory_children(local_data / "cache")
    stats["worktrees_removed"] = _clear_directory_children(local_data / "worktrees")
    stats["repo_clones_removed"] = _clear_directory_children(clone_root)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="清空 DiffGate 仓库与分析数据")
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="跳过确认",
    )
    args = parser.parse_args()
    if not args.yes:
        print("将删除：所有 repositories、analysis_jobs、克隆目录、任务图缓存（保留用户登录数据）。")
        try:
            ans = input("确认清空？[y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("y", "yes"):
            print("已取消")
            return 1
    stats = reset_platform_data()
    print("已清空平台数据：")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())