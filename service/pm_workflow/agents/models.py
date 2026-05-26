"""Agent 间共享的 pydantic 模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pm_workflow.scrapers.tavily import TavilyResult


class CompetitorSnapshot(BaseModel):
    """单个竞品的调研快照。"""

    name: str
    reason: str = ""  # 为什么列入（来自 LLM 推断或用户指定）
    source: str = "user"  # user / llm
    tavily_answer: str | None = None  # Tavily 给的 1-2 句总结
    tavily_results: list[TavilyResult] = Field(default_factory=list)


class ResearchResult(BaseModel):
    """调研 agent 的输出。"""

    req_id: str
    req_page_id: str
    requirement_name: str
    scenario: str
    competitors: list[CompetitorSnapshot]
    research_markdown: str  # 最终的 research.md 内容
    output_path: str = ""  # 落盘后的本地路径
    llm_usage: dict = Field(default_factory=dict)  # 累计 token 用量（成本核算）
    errors: list[str] = Field(default_factory=list)  # 非致命错误集合
