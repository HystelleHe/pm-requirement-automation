"""飞书自定义机器人通知 —— 无 OAuth，直接 POST webhook 即可。

设计：
- 三个 stage（research / breakdown / prd）的成功/失败事件统一走 Notifier.send_stage()
- 未配置 FEISHU_WEBHOOK_URL 时降级为 stdout 打印，不阻塞业务（兜底）
- 任何 webhook 失败都吞掉 + 记日志，绝不让通知阻断主流程
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

import httpx

from pm_workflow.config import Settings, get_settings

logger = logging.getLogger(__name__)


Stage = Literal["research", "breakdown", "prd"]
Outcome = Literal["success", "failure"]


@dataclass
class StageEvent:
    """单次 stage 完成/失败事件。"""

    stage: Stage
    outcome: Outcome
    requirement_name: str
    req_id: str
    summary: str = ""  # 一行摘要，如「4 竞品，2751 tokens」「11 用户故事，5074 tokens」
    detail_url: str = ""  # 产出页面 URL（Notion 子页面链接）
    failure_reason: str = ""  # outcome=failure 时填


_STAGE_LABEL: dict[Stage, str] = {
    "research": "竞品调研",
    "breakdown": "需求拆解",
    "prd": "PRD 生成",
}


def _build_card_payload(event: StageEvent) -> dict:
    """构造飞书 interactive 卡片消息。

    飞书自定义机器人卡片协议：msg_type=interactive，card 结构 ≈ block-based UI。
    参考：https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/im-v1/message/create_json
    """
    label = _STAGE_LABEL.get(event.stage, event.stage)
    color = "green" if event.outcome == "success" else "red"
    title_emoji = "✅" if event.outcome == "success" else "❌"
    title = f"{title_emoji} {label} - {event.requirement_name}"

    elements: list[dict] = [
        {
            "tag": "div",
            "fields": [
                {
                    "is_short": True,
                    "text": {"tag": "lark_md", "content": f"**Stage**\n{label}"},
                },
                {
                    "is_short": True,
                    "text": {"tag": "lark_md", "content": f"**req_id**\n{event.req_id}"},
                },
            ],
        }
    ]

    if event.summary:
        elements.append(
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**摘要**：{event.summary}"}}
        )

    if event.outcome == "failure" and event.failure_reason:
        # 飞书卡片单元素 content 上限较保守，截到 800 字防止整条消息被拒
        reason = event.failure_reason[:800]
        if len(event.failure_reason) > 800:
            reason += "..."
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**失败原因**\n```\n{reason}\n```"},
            }
        )

    if event.detail_url:
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "查看详情"},
                        "url": event.detail_url,
                        "type": "primary",
                    }
                ],
            }
        )

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": color,
                "title": {"tag": "plain_text", "content": title},
            },
            "elements": elements,
        },
    }


class Notifier:
    """统一通知入口；agent 端调 send_stage() 不关心 webhook 细节。"""

    def __init__(self, *, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.feishu_webhook_url)

    def send_stage(self, event: StageEvent) -> None:
        """发送一次 stage 事件通知。webhook 未配置或失败都不抛，仅记日志。"""
        if not self.enabled:
            # stdout fallback：用 print 而不是 logger.info，确保未配 webhook 时
            # 仍能在终端/容器日志看到「事件已触发但被吞了」，便于排查
            mark = "✅" if event.outcome == "success" else "❌"
            extra = f" | 详情: {event.detail_url}" if event.detail_url else ""
            if event.outcome == "failure":
                extra += f" | 失败: {event.failure_reason[:200]}"
            print(
                f"[notifier:stdout] {mark} stage={event.stage} req={event.requirement_name} "
                f"({event.req_id}) | {event.summary or '(空)'}{extra}",
                flush=True,
            )
            return

        payload = _build_card_payload(event)
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(self.settings.feishu_webhook_url, json=payload)
                resp.raise_for_status()
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                # 飞书返回 {"code": 0, "msg": "ok"} 表示成功；非 0 是配置/格式错
                if isinstance(body, dict) and body.get("code", 0) != 0:
                    logger.warning(
                        "飞书 webhook 返回非 0 code（不阻塞）：%s",
                        json.dumps(body, ensure_ascii=False),
                    )
        except Exception as e:
            logger.warning("飞书通知失败（不阻塞主流程）：%s: %s", type(e).__name__, e)
