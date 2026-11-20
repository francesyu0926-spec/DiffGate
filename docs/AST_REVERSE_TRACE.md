# 基于 AST 的逆向接口追溯引擎

DiffGate 将设计文档中的四步落地为 `ReverseTraceEngine`（`app/engine/reverse_trace.py`）。

## 第一步：全量扫描，构建静态调用图

| 设计要点 | 实现 |
|---------|------|
| AST 拆解类/函数/调用 | `app/parsers/python_ast.py` |
| 函数起止行号 | `SymbolDef.start_line` / `end_line` |
| 顶层 API 节点（`@router.post` / `@app.post`） | `is_api_handler`、`route_path` |
| 反向索引「B 被 A 调用」 | `CallGraph.reverse` → Redis / Neo4j |

## 第二步：监听提交，Git Diff 定位「案发现场」

| 设计要点 | 实现 |
|---------|------|
| 精确变更行 | `app/parsers/git_diff.py` |
| 行号匹配函数区间 | `ReverseTraceEngine.step2_locate_suspects` → **嫌疑函数** |

## 第三步：反向图 BFS 追溯

| 设计要点 | 实现 |
|---------|------|
| 层序向上查找调用者 | `CallGraph.resolve_callers` / `reverse_bfs_traces`（`deque` BFS） |
| 环与递归 | **`visited` 集合**，已访问节点不再入队 |
| 输出调用链 | `chain` / `chain_labels`，例：`calc_price → create_order_service → POST /api/v1/order` |

## 第四步：影响面报告 + 精准回归联动

| 设计要点 | 实现 |
|---------|------|
| 受影响接口清单 | `ImpactReport.affected_apis` |
| 拓扑路径给前端 G6 | `build_g6_payload` + `GET /jobs/{id}/graph` |
| 调度中心 | `DISPATCH_CENTER_URL` → `notify_dispatch_center` |

### 调度中心 Payload 示例

```json
{
  "job_id": "...",
  "repo": "group/project",
  "interfaces": [
    {"method": "POST", "path": "/api/v1/order"},
    {"method": "PUT", "path": "/api/v1/cart"}
  ],
  "call_paths": [
    {
      "method": "POST",
      "path": "/api/v1/order",
      "chain_labels": ["calc_price", "create_order_service", "POST /api/v1/order"]
    }
  ]
}
```

仅执行上述接口关联用例，跳过无关接口回归。