"""Notion 数据库行的 Pydantic 模型。

只包含本项目真正用到的字段；Skill Library 30+ 列我们只读写 10 列子集，
其它列不动以保持与用户原有用途兼容。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ===================================================================
# A. PM 需求表（触发源）
# ===================================================================


class RequirementStatus(str, Enum):
    """需求表 状态 字段的可选值（与 Notion select option 完全对应）。"""

    PENDING = "待处理"
    RESEARCHING = "调研中"
    BREAKING_DOWN = "拆解中"
    WRITING_PRD = "PRD生成中"
    GENERATING_INSIGHT = "洞察生成中"  # Discover 路径专用
    DONE = "已完成"
    FAILED = "失败"


class RequirementType(str, Enum):
    """需求类型 —— 人工选；决定走哪条路径。"""

    BUILD = "Build"  # 功能需求 → research → breakdown → PRD
    DISCOVER = "Discover"  # 探索调研 → research → insight_memo


class Requirement(BaseModel):
    """PM 需求表的一行。"""

    page_id: str  # Notion page UUID
    name: str  # 需求名称（title）
    scenario: str = ""  # 场景描述
    competitors: list[str] = Field(default_factory=list)  # 指定竞品 multi_select
    keywords: str = ""  # 自动发现关键词（由 agent 填回）
    status: RequirementStatus = RequirementStatus.PENDING
    type: RequirementType = RequirementType.BUILD  # 空值 fallback Build（向后兼容）
    research_url: str | None = None  # 调研报告链接
    breakdown_url: str | None = None  # 需求拆解链接
    prd_url: str | None = None  # PRD 链接
    insight_url: str | None = None  # 洞察备忘录链接（Discover 路径）
    failure_reason: str = ""  # 失败原因
    req_id: str = ""  # 对应 outputs/{req_id}/
    created_time: datetime | None = None


# ===================================================================
# B. Skill Library（10 字段子集；其它列不读不写）
# ===================================================================


class SkillStatus(str, Enum):
    DRAFT = "Draft"
    ACTIVE = "Active"
    DEPRECATED = "Deprecated"


class Skill(BaseModel):
    """Skill Library 的一行（10 字段子集）。

    注意：本地 skill-library/*.md 的 frontmatter 必须严格使用这些字段名。
    """

    page_id: str | None = None  # Notion page UUID（新建时 None）
    name: str  # Name (title)
    skill_key: str  # Skill Key（唯一标识，代码里通过这个引用）
    status: SkillStatus = SkillStatus.DRAFT
    version: str = "0.1.0"
    description: str = ""  # Description（简介）
    system_prompt: str = ""  # System Prompt
    user_prompt_template: str = ""  # User Prompt Template（含 {{var}}）
    input_variables: str = ""  # Input Variables（JSON 字符串声明变量列表）
    output_schema: str = ""  # Output Schema（JSON 字符串声明返回结构）
    model_preference: str = "auto"  # auto/claude/gpt/moonshot/deepseek
    pipeline: list[str] = Field(default_factory=list)  # 适用管线 multi_select：竞品调研/PRD/Figma
