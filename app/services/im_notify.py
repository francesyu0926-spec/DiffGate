"""飞书 / 钉钉 / 企业微信 Webhook 卡片（门禁通知）。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.db.models import AnalysisJob, Repository
from app.services.quality_gate import reconciled_coverage_stats

logger = logging.getLogger(__name__)

NotifyPolicy = str  # off | block_only | always


def repo_notify_webhook(repo: Repository | None) -> str:
    if not repo:
        return ""
    url = (getattr(repo, "notify_webhook_url", None) or getattr(repo, "webhook_notify_url", None) or "")
    return str(url).strip()


def repo_notify_policy(repo: Repository | None) -> NotifyPolicy:
    if not repo:
        return "block_only"
    policy = str(getattr(repo, "notify_policy", None) or "block_only").strip().lower()
    if policy in ("off", "block_only", "always"):
        return policy
    return "block_only"


def should_send_im(repo: Repository | None, gate: str) -> bool:
    policy = repo_notify_policy(repo)
    g = (gate or "").upper()
    if policy == "off":
        return False
    if policy == "always":
        return g in ("PASS", "BLOCK", "OVERRIDDEN", "PENDING")
    return g == "BLOCK"


def webhook_vendor_from_url(url: str) -> str:
    u = (url or "").lower()
    if "feishu" in u or "lark" in u or "larksuite" in u:
        return "feishu"
    if "dingtalk" in u or "oapi.dingtalk.com" in u:
        return "dingtalk"
    if "qyapi.weixin.qq.com" in u or "weixin.qq.com/cgi-bin/webhook" in u:
        return "wecom"
    return "custom"


def _pick_webhook(repo: Repository | None) -> tuple[str, str]:
    settings = get_settings()
    custom = repo_notify_webhook(repo)
    if custom:
        return custom, webhook_vendor_from_url(custom)
    if settings.feishu_webhook_url:
        return settings.feishu_webhook_url, "feishu"
    if settings.dingtalk_webhook_url:
        return settings.dingtalk_webhook_url, "dingtalk"
    if settings.wecom_webhook_url:
        return settings.wecom_webhook_url, "wecom"
    return "", ""


def regression_link(job_id: str, *, action: str | None = None) -> str:
    settings = get_settings()
    base = (settings.web_app_public_base_url or settings.api_public_base_url).rstrip("/")
    q = quote(job_id)
    extra = f"&action={action}" if action else ""
    return f"{base}/regression?job_id={q}{extra}"


def _branch_label(job: AnalysisJob) -> str:
    ref = (getattr(job, "ref", None) or "").strip()
    return ref.replace("refs/heads/", "") or "—"


def _trigger_summary(gr: dict) -> str:
    td = gr.get("trigger_detail")
    if isinstance(td, dict) and td.get("summary"):
        return str(td["summary"])
    return str(gr.get("block_reason_label") or gr.get("block_reason") or "—")


def _feishu_card(
    job: AnalysisJob,
    gr: dict,
    *,
    summary_lines: list[str],
    regression_url: str,
    override_url: str,
    header_color: str,
) -> dict[str, Any]:
    gate = str(gr.get("gate") or "PENDING")
    title = f"DiffGate · {gate} · {job.repo_full_name}"
    elements: list[dict[str, Any]] = [
        {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(summary_lines)}},
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "前往精准回归"},
                    "url": regression_url,
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "人工豁免"},
                    "type": "primary",
                    "url": override_url,
                },
            ],
        },
    ]
    return {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": title}, "template": header_color},
            "elements": elements,
        },
    }


def _markdown_text(summary_lines: list[str], regression_url: str, override_url: str) -> str:
    body = "\n".join(f"- {line}" for line in summary_lines)
    return f"{body}\n\n[前往精准回归]({regression_url}) · [人工豁免]({override_url})"


def build_im_payload(
    job: AnalysisJob,
    gr: dict,
    *,
    vendor: str,
    regression_url: str,
    override_url: str,
) -> dict[str, Any]:
    cov_pct, _, _ = reconciled_coverage_stats(gr)
    th = gr.get("coverage_threshold")
    cov_s = f"{cov_pct}%" if cov_pct is not None else str(gr.get("incremental_coverage_pct") or "待回传")
    meta = getattr(job, "job_metadata", None) or {}
    committer = str(meta.get("committer") or "—")
    aa = getattr(job, "affected_apis", None) or {}
    apis = int(gr.get("api_impact") or (aa.get("count") if isinstance(aa, dict) else 0) or 0)
    lines = int(gr.get("changed_lines") or 0)
    gate = str(gr.get("gate") or "PENDING")

    summary_lines = [
        f"**仓库** {job.repo_full_name}",
        f"**分支** {_branch_label(job)} · **Commit** `{(job.head_sha or '')[:8]}`",
        f"**变更规模** {lines} 行 · 影响 API {apis} 个",
        f"**增量覆盖率** {cov_s}" + (f"（阈值 {th}%）" if th is not None else ""),
        f"**门禁** {gate} · {_trigger_summary(gr)}",
        f"**提交人** {committer}",
    ]

    header_color = "red" if gate == "BLOCK" else "green" if gate in ("PASS", "OVERRIDDEN") else "blue"

    if vendor in ("feishu", "custom", "lark") or "feishu" in vendor:
        return _feishu_card(
            job,
            gr,
            summary_lines=summary_lines,
            regression_url=regression_url,
            override_url=override_url,
            header_color=header_color,
        )
    text = _markdown_text(summary_lines, regression_url, override_url)
    if vendor == "dingtalk":
        return {"msgtype": "markdown", "markdown": {"title": "DiffGate 门禁", "text": text}}
    if vendor == "wecom":
        return {"msgtype": "markdown", "markdown": {"content": text}}
    return {"msg_type": "text", "content": {"text": text}}


def send_gate_im_notice(job: AnalysisJob, repo: Repository | None, gr: dict) -> dict[str, Any]:
    """发送 IM 通知并返回 notify_status 结构（写入 gate_result）。"""
    now = datetime.utcnow().isoformat() + "Z"
    gate = str(gr.get("gate") or "")
    if not should_send_im(repo, gate):
        return {"sent": False, "sent_at": None, "error_msg": "notify_policy_skip"}

    webhook, vendor = _pick_webhook(repo)
    if not webhook:
        return {"sent": False, "sent_at": None, "error_msg": "no_webhook_configured"}

    regression_url = regression_link(job.id)
    override_url = regression_link(job.id, action="override")
    payload = build_im_payload(
        job,
        gr,
        vendor=vendor,
        regression_url=regression_url,
        override_url=override_url,
    )
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(webhook, json=payload)
            resp.raise_for_status()
        return {"sent": True, "sent_at": now, "error_msg": None, "platform": vendor}
    except Exception as exc:
        logger.warning("im notify failed: %s", exc)
        return {"sent": False, "sent_at": now, "error_msg": str(exc)[:500], "platform": vendor}


def send_im_block_notice(job: AnalysisJob, repo: Repository | None, gr: dict) -> None:
    send_gate_im_notice(job, repo, gr)


def send_test_notify(webhook_url: str) -> dict[str, Any]:
    vendor = "feishu" if "feishu" in webhook_url or "lark" in webhook_url else "custom"
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "DiffGate 连通性测试"}, "template": "blue"},
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "这是一条测试卡片，表示 Webhook 配置有效。",
                    },
                }
            ],
        },
    }
    if "feishu" not in webhook_url and "lark" not in webhook_url:
        payload = {"msg_type": "text", "content": {"text": "DiffGate IM 连通性测试"}}
    try:
        with httpx.Client(timeout=12.0) as client:
            client.post(webhook_url, json=payload).raise_for_status()
        return {"success": True, "platform": vendor, "message": "测试卡片发送成功"}
    except Exception as exc:
        return {"success": False, "platform": vendor, "message": str(exc)[:300]}