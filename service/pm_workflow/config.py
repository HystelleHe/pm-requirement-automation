"""集中配置 —— 从 .env 加载所有外部依赖项。

设计原则：
- 所有外部 KEY / URL / 路由模型名都通过环境变量注入，不在代码里写死
- 启动时用 pydantic-settings 验证，缺关键变量直接报错而不是运行时崩溃
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# 项目根目录：service/ 的上一级
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """从 .env 读取的全部运行时配置。"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env 里多出来的变量（如 POSTGRES_*）不报错
    )

    # === LLM 网关 ===
    llm_gateway_url: str = Field(default="https://api.modelverse.cn/v1", alias="LLM_GATEWAY_URL")
    llm_gateway_token: str = Field(default="", alias="LLM_GATEWAY_TOKEN")

    # === 模型路由（任务 → 模型）===
    llm_model_keyword_discovery: str = Field(
        default="moonshotai/Kimi-K2-Thinking", alias="LLM_MODEL_KEYWORD_DISCOVERY"
    )
    llm_model_breakdown: str = Field(default="moonshotai/Kimi-K2-Thinking", alias="LLM_MODEL_BREAKDOWN")
    llm_model_prd_writer: str = Field(default="moonshotai/Kimi-K2-Thinking", alias="LLM_MODEL_PRD_WRITER")
    llm_model_web_summary: str = Field(default="deepseek-v4-flash", alias="LLM_MODEL_WEB_SUMMARY")
    llm_model_prd_critic: str = Field(default="glm-5-turbo", alias="LLM_MODEL_PRD_CRITIC")
    llm_model_eval_judge: str = Field(default="glm-5-turbo", alias="LLM_MODEL_EVAL_JUDGE")

    # === Notion ===
    notion_api_key: str = Field(default="", alias="NOTION_API_KEY")
    notion_db_requirements: str = Field(default="", alias="NOTION_DB_REQUIREMENTS")
    notion_db_skill_library: str = Field(default="", alias="NOTION_DB_SKILL_LIBRARY")
    notion_db_research_cache: str = Field(default="", alias="NOTION_DB_RESEARCH_CACHE")
    notion_db_eval: str = Field(default="", alias="NOTION_DB_EVAL")
    notion_parent_page_id: str = Field(default="", alias="NOTION_PARENT_PAGE_ID")

    # === 搜索服务 ===
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    perplexity_api_key: str = Field(default="", alias="PERPLEXITY_API_KEY")

    # === Langfuse 观测 ===
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="http://langfuse:3000", alias="LANGFUSE_HOST")

    # === Service ===
    service_port: int = Field(default=8000, alias="SERVICE_PORT")

    # === 成本控制 ===
    cost_budget_per_request_usd: float = Field(default=3.0, alias="COST_BUDGET_PER_REQUEST_USD")
    critic_max_rounds: int = Field(default=2, alias="CRITIC_MAX_ROUNDS")

    # === 项目路径（运行时计算，不来自 env）===
    @property
    def skill_library_dir(self) -> Path:
        """本地 skill-library/ 目录的绝对路径（Prompt SoT）。"""
        return PROJECT_ROOT / "skill-library"

    @property
    def outputs_dir(self) -> Path:
        """产出目录 outputs/{req_id}/。"""
        return PROJECT_ROOT / "outputs"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例配置；进程内缓存，避免重复读 .env。"""
    return Settings()
