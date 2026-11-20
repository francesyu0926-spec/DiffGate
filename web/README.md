# DiffGate Web（Vue 3）

默认前端：**Vue 3 + Vite + TypeScript + Vuetify 3（Material Design 3）+ AntV G6**。

- 全局壳层、导航、变更影响列表：**Vuetify 3**（`src/plugins/vuetify.ts`，`md3` blueprint）
- 仓库管理 / 质量驾驶舱 / 任务详情：过渡期仍含 **Element Plus** 表单与表格，可逐步替换为 `v-data-table` / `v-dialog`

- 任务列表：`/`
- 任务详情 + 调用链图：`/jobs/:id`

## 开发

```powershell
# 后端 API 需在 8000 端口运行
..\scripts\run_web.ps1
```

浏览器访问：`http://localhost:5173`（Vite 代理 `/api` → FastAPI）。

## React 18 + G6 方案

若团队更熟悉 React，可新建 `web-react/` 并复用同一套 API：

- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{id}`
- `GET /api/v1/jobs/{id}/graph`

图数据已是 G6 可直接消费的 `nodes/edges` 结构；React 侧仅需 `@antv/g6` + `useEffect` 挂载即可。