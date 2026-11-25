# 本地运行后端（无 Docker）

## 极简模式（推荐）

**不需要**：Docker、MySQL、Redis、Neo4j、独立 Celery Worker。

| 组件 | 替代 |
|------|------|
| MySQL | SQLite `data/diffgate.db` |
| Redis 图缓存 | `data/cache/` 本地 JSON |
| Neo4j | `USE_NEO4J=false` |
| Celery Worker | `CELERY_ALWAYS_EAGER=true` 在 API 进程内同步执行任务 |

### 步骤（Windows PowerShell）

```powershell
cd "D:\Document\AI LAB\DiffGate"
.\scripts\setup_local.ps1
.\scripts\run_local.ps1
```

- 健康检查：http://127.0.0.1:8000/health  
- API 文档：http://127.0.0.1:8000/docs  

若在 Windows 上重启 API 后仍提示端口占用、或 `8000` 只响应旧版接口，先清理残留 worker：

```powershell
.\scripts\kill_stale_api.ps1
.\scripts\run_api.ps1
```

`run_api.ps1` 启动前会自动调用清理脚本（`uvicorn --reload` 偶发遗留孤儿进程）。

### 不连 Webhook 时自测分析

```powershell
$env:PYTHONPATH = "."
$env:PIP_REQUIRE_HASHES = "0"
.\.venv\Scripts\python -m scripts.analyze_local --repo tests\fixtures\sample_app --base HEAD --head HEAD --no-neo4j
```

---

## 进阶：本机安装 Redis + MySQL（仍不用 Docker）

若要 **异步 Worker**、Webhook 高并发：

1. 本机安装 [Memurai](https://www.memurai.com/) 或 Redis，默认 `6379`  
2. 安装 MySQL 8，建库 `diffgate`，用户见 `.env.example`  
3. `.env` 使用 `.env.example` 配置，并设 `CELERY_ALWAYS_EAGER=false`  
4. 两个终端：

```powershell
.\scripts\run_api.ps1
.\scripts\run_worker.ps1
```

Neo4j 仍为可选；仅在需要图数据库查询时安装并设 `USE_NEO4J=true`。