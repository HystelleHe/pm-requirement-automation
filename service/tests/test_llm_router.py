"""LLMRouter 单测 —— 用 mock 验证路由逻辑，不触达网络。"""

from unittest.mock import MagicMock, patch

import pytest

from pm_workflow.config import Settings
from pm_workflow.llm import ChatResponse, LLMRouter, LLMTask


def _settings_with_token(**overrides) -> Settings:
    defaults = {
        "LLM_GATEWAY_URL": "http://test/v1",
        "LLM_GATEWAY_TOKEN": "test-token",
    }
    defaults.update(overrides)
    import os

    env_backup = {k: os.environ.get(k) for k in defaults}
    try:
        for k, v in defaults.items():
            os.environ[k] = v
        return Settings()
    finally:
        for k, v in env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_router_missing_token_raises():
    """没有 LLM_GATEWAY_TOKEN 时初始化应该失败。"""
    s = Settings(LLM_GATEWAY_TOKEN="")
    with pytest.raises(RuntimeError, match="LLM_GATEWAY_TOKEN"):
        LLMRouter(settings=s)


def test_router_model_for_each_task():
    """所有 LLMTask 都应能查到模型名（即每个任务都有 .env 默认值）。"""
    s = _settings_with_token()
    with patch("pm_workflow.llm.router._build_openai_client", return_value=(MagicMock(), False)):
        router = LLMRouter(settings=s)
    for task in LLMTask:
        assert router.model_for(task), f"task {task.value} 缺少模型映射"


def test_router_chat_parses_response_with_reasoning():
    """验证 chat 调用返回 ChatResponse，且 reasoning_content 被正确抽出。"""
    fake_client = MagicMock()
    fake_message = MagicMock()
    fake_message.model_dump.return_value = {
        "role": "assistant",
        "content": "hello",
        "reasoning_content": "我正在思考",
    }
    fake_choice = MagicMock()
    fake_choice.message = fake_message
    fake_choice.finish_reason = "stop"
    fake_usage = MagicMock()
    fake_usage.model_dump.return_value = {
        "prompt_tokens": 5,
        "completion_tokens": 20,
        "completion_tokens_details": {"reasoning_tokens": 15},
    }
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_resp.usage = fake_usage
    fake_client.chat.completions.create.return_value = fake_resp

    s = _settings_with_token()
    with patch("pm_workflow.llm.router._build_openai_client", return_value=(fake_client, False)):
        router = LLMRouter(settings=s)
    out = router.chat(LLMTask.BREAKDOWN, [{"role": "user", "content": "test"}])

    assert isinstance(out, ChatResponse)
    assert out.content == "hello"
    assert out.reasoning == "我正在思考"
    assert out.task == LLMTask.BREAKDOWN
    assert out.finish_reason == "stop"
    assert out.usage["completion_tokens_details"]["reasoning_tokens"] == 15
    # 调用透传了正确的 model
    called_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert called_kwargs["model"] == s.llm_model_breakdown
