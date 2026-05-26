"""Agent 间共享的 pydantic 模型。"""

from __future__ import annotations

from typing import Literal

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


# ===================================================================
# Phase 3: 需求拆解
# ===================================================================


Priority = Literal["P0", "P1", "P2"]


class UserStory(BaseModel):
    """单条用户故事 + 优先级 + 验收标准。"""

    story: str  # "作为 ... 我希望 ... 以便 ..."
    priority: Priority = "P1"
    rationale: str = ""  # 为什么是这个优先级
    acceptance_criteria: list[str] = Field(default_factory=list)


class BreakdownResult(BaseModel):
    """拆解 agent 的输出。"""

    req_id: str
    req_page_id: str
    requirement_name: str
    user_stories: list[UserStory]
    out_of_scope: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    breakdown_markdown: str = ""  # 渲染好的 breakdown.md 内容
    output_path: str = ""
    llm_usage: dict = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


# ===================================================================
# Phase 4: PRD 撰写 + Critic 修订循环
# ===================================================================


Severity = Literal["P0", "P1", "P2"]


class CriticIssue(BaseModel):
    """Critic 模型抛出的单条问题。"""

    severity: Severity = "P1"
    section: str = ""  # 章节名（背景/目标/用户故事/...）
    problem: str
    suggestion: str = ""


class CriticReview(BaseModel):
    """一轮 Critic 审校的完整结果。"""

    round: int  # 第几轮（从 1 开始）
    overall_score: int = 0  # 0-100
    needs_revision: bool = False
    issues: list[CriticIssue] = Field(default_factory=list)
    summary: str = ""
    llm_usage: dict = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class PRDResult(BaseModel):
    """PRD agent 的输出（含修订历史）。"""

    req_id: str
    req_page_id: str
    requirement_name: str
    prd_markdown: str = ""  # 最终版 PRD
    revisions: int = 0  # 经过几轮修订（0 表示初版即过）
    reviews: list[CriticReview] = Field(default_factory=list)  # 每轮 critic 结果
    output_path: str = ""
    llm_usage: dict = Field(default_factory=dict)  # 累计 token
    errors: list[str] = Field(default_factory=list)
