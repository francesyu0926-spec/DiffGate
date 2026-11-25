# 用 ngrok 暴露 Webhook（本地 → 公网）

## 前提

1. API 已启动：`.\scripts\run_api.ps1`（默认 `0.0.0.0:8000`）
2. [ngrok](https://ngrok.com/) 已安装并配置 authtoken：

```powershell
winget install ngrok.ngrok
ngrok config add-authtoken <token>
```

## 一键配置

```powershell
.\scripts\setup_webhook_ngrok.ps1 -InstallNgrok
```

脚本会：

- 在 `.env` 中生成 `WEBHOOK_SECRET_GITHUB` / `WEBHOOK_SECRET_GITLAB`（若为空）
- 启动 `ngrok http 8000` 并写入 `WEBHOOK_PUBLIC_BASE_URL`
- 打印 GitHub / GitLab 要填的 URL 与 Secret
- 调用 `test_webhook_ping.ps1` 模拟 GitHub `ping`

**改 `.env` 后必须重启 API**，否则签名校验仍用旧 Secret。

## 在 Git 平台配置

| 平台 | Payload URL | Secret |
|------|-------------|--------|
| GitHub | `https://<ngrok>/api/v1/webhooks/github` | 与 `.env` 中 `WEBHOOK_SECRET_GITHUB` 一致 |
| GitLab | `https://<ngrok>/api/v1/webhooks/gitlab` | 与 `.env` 中 `WEBHOOK_SECRET_GITLAB` 一致（Secret token） |

事件：Push + PR/MR。推送后打开 DiffGate **变更影响分析** 查看任务。

## 仅启动隧道

```powershell
ngrok http 8000
```

将控制台里的 `Forwarding` HTTPS 地址写入 `.env`：

```env
WEBHOOK_PUBLIC_BASE_URL=https://xxxx.ngrok-free.app
```

前端顶栏 **Webhook 指引** 会显示该公网地址（需 API 重启后读取 `.env`）。

## 自检

```powershell
.\scripts\test_webhook_ping.ps1
```