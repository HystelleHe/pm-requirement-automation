"""LLM 路由器 —— 按任务名映射到 modelverse 网关上的具体模型。

设计：
- 一个 OpenAI 兼容 client 走 modelverse；不同任务用不同 model 名
- 如果配置了 Langfuse 凭据，自动用 langfuse.openai 替代以记录 trace
- 否则降级为原生 openai SDK，不影响运行
- 返回结构化的 ChatResponse，把 reasoning_content 和 usage 拆开方便后续成本核算
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from pydantic import BaseModel

from pm_workflow.config import Settings, get_settings

logger = logging.getLogger(__name__)


class LLMTask(str, Enum):
    """业务任务到 .env 里 LLM_MODEL_* 变量的映射键。"""

    KEYWORD_DISCOVERY = "keyword_discovery"
    BREAKDOWN = "breakdown"
    PRD_WRITER = "prd_writer"
    WEB_SUMMARY = "web_summary"
    PRD_CRITIC = "prd_critic"
    EVAL_JUDGE = "eval_judge"


class ChatResponse(BaseModel):
    """统一封装 LLM 响应，方便上层处理。"""

    task: LLMTask
    model: str
    content: str
    # reasoning 类模型独有：思考过程；非 reasoning 模型为 None
    reasoning: str | None = None
    # token 用量：所有 reasoning 模型都会消耗 reasoning_tokens（成本核算用）
    usage: dict[str, Any] = {}
    # 完成原因：stop / length / content_filter / tool_calls
    finish_reason: str | None = None


def _build_openai_client(settings: Settings):
    """根据 langfuse 配置决定用 langfuse.openai（带 trace）还是原生 openai。

    Langfuse SDK 提供的 langfuse.openai.OpenAI 是原生 OpenAI 的 drop-in 替代，
    自动 capture 每次调用为 trace。没配 langfuse 凭据时降级为原生，不挂业务。
    """
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        try:
            from langfuse.openai import OpenAI as TracedOpenAI  # type: ignore

            logger.info("LLM client：langfuse traced OpenAI 已启用")
            return TracedOpenAI(
                api_key=settings.llm_gateway_token,
                base_url=settings.llm_gateway_url,
            ), True
        except Exception as e:
            logger.warning("Langfuse 接入失败，降级为原生 openai：%s", e)

    from openai import OpenAI

    logger.info("LLM client：原生 OpenAI（无 trace）")
    return OpenAI(
        api_key=settings.llm_gateway_token,
        base_url=settings.llm_gateway_url,
    ), False


class LLMRouter:
    """业务侧统一入口：router.chat(LLMTask.PRD_WRITER, messages)。"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        if not self.settings.llm_gateway_token:
            raise RuntimeError("LLM_GATEWAY_TOKEN 未配置，无法初始化 LLMRouter")
        self.client, self.traced = _build_openai_client(self.settings)

    def model_for(self, task: LLMTask) -> str:
        """从 settings 查任务对应的 modelverse 模型名。"""
        return getattr(self.settings, f"llm_model_{task.value}")

    def chat(
        self,
        task: LLMTask,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """同步调用：单次 chat completion。

        参数遵循 OpenAI 协议；额外的 kwargs 透传给底层 SDK。
        """
        model = self.model_for(task)
        params: dict[str, Any] = {"model": model, "messages": messages}
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if temperature is not None:
            params["temperature"] = temperature
        params.update(kwargs)

        resp = self.client.chat.completions.create(**params)
        choice = resp.choices[0]
        msg_dict = choice.message.model_dump()  # 拿到所有字段（含 SDK 没声明的 reasoning_content）
        usage_dict = resp.usage.model_dump() if resp.usage else {}

        return ChatResponse(
            task=task,
            model=model,
            content=msg_dict.get("content") or "",
            reasoning=msg_dict.get("reasoning_content"),
            usage=usage_dict,
            finish_reason=choice.finish_reason,
        )
