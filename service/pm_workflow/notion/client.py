"""Notion 客户端 —— 封装 notion-client SDK，提供业务级方法。

提供给上层的能力：
- query_requirements(status) → 读需求表
- update_requirement(page_id, **fields) → 写状态/URL/失败原因
- list_skills() → 读 Skill Library 的 10 字段子集
- upsert_skill(skill) → 按 skill_key 决定 create 还是 update（仅写 10 列子集）
"""

from __future__ import annotations

import logging
from typing import Any

from notion_client import Client as NotionSDK

from pm_workflow.config import Settings, get_settings
from pm_workflow.notion.models import (
    Requirement,
    RequirementStatus,
    Skill,
    SkillStatus,
)

logger = logging.getLogger(__name__)


# ===================================================================
# Notion property 解构 / 构造工具函数
# Notion API 的 property 值结构嵌套很深，集中放这里复用
# ===================================================================


def _title(prop: dict) -> str:
    arr = prop.get("title", [])
    return "".join(x.get("plain_text", "") for x in arr).strip()


def _rich_text(prop: dict) -> str:
    arr = prop.get("rich_text", [])
    return "".join(x.get("plain_text", "") for x in arr).strip()


def _select(prop: dict) -> str | None:
    val = prop.get("select")
    return val.get("name") if val else None


def _multi_select(prop: dict) -> list[str]:
    return [x.get("name", "") for x in prop.get("multi_select", []) if x.get("name")]


def _url(prop: dict) -> str | None:
    return prop.get("url")


def _checkbox(prop: dict) -> bool:
    return bool(prop.get("checkbox"))


def _date_start(prop: dict) -> str | None:
    d = prop.get("date") or {}
    return d.get("start")


def _created_time(prop: dict) -> str | None:
    return prop.get("created_time")


def _to_rich_text(text: str) -> list[dict]:
    """字符串 → Notion rich_text 数组。空串返回空数组。"""
    return [{"type": "text", "text": {"content": text}}] if text else []


def _to_title(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": text}}]


# ===================================================================
# NotionClient 主类
# ===================================================================


class NotionClient:
    """业务侧统一入口。"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        if not self.settings.notion_api_key:
            raise RuntimeError("NOTION_API_KEY 未配置，无法初始化 NotionClient")
        self.sdk = NotionSDK(auth=self.settings.notion_api_key)

    # ----------------------- 需求表 -----------------------

    def query_requirements(
        self,
        status: RequirementStatus | str | None = RequirementStatus.PENDING,
    ) -> list[Requirement]:
        """查需求表；status=None 表示不过滤，返回全部。"""
        filter_: dict[str, Any] | None = None
        if status is not None:
            status_str = status.value if isinstance(status, RequirementStatus) else status
            filter_ = {"property": "状态", "select": {"equals": status_str}}

        params: dict[str, Any] = {"database_id": self.settings.notion_db_requirements}
        if filter_:
            params["filter"] = filter_
        resp = self.sdk.databases.query(**params)
        return [self._row_to_requirement(row) for row in resp.get("results", [])]

    def _row_to_requirement(self, row: dict) -> Requirement:
        p = row["properties"]
        status_str = _select(p.get("状态", {}))
        try:
            status = RequirementStatus(status_str) if status_str else RequirementStatus.PENDING
        except ValueError:
            status = RequirementStatus.PENDING
        return Requirement(
            page_id=row["id"],
            name=_title(p.get("需求名称", {})),
            scenario=_rich_text(p.get("场景描述", {})),
            competitors=_multi_select(p.get("指定竞品", {})),
            keywords=_rich_text(p.get("自动发现关键词", {})),
            status=status,
            research_url=_url(p.get("调研报告链接", {})),
            breakdown_url=_url(p.get("需求拆解链接", {})),
            prd_url=_url(p.get("PRD链接", {})),
            failure_reason=_rich_text(p.get("失败原因", {})),
            req_id=_rich_text(p.get("req_id", {})),
        )

    def update_requirement(
        self,
        page_id: str,
        *,
        status: RequirementStatus | str | None = None,
        keywords: str | None = None,
        research_url: str | None = None,
        breakdown_url: str | None = None,
        prd_url: str | None = None,
        failure_reason: str | None = None,
        req_id: str | None = None,
    ) -> None:
        """部分更新需求表行。传 None 的字段保持不变。"""
        props: dict[str, Any] = {}
        if status is not None:
            s = status.value if isinstance(status, RequirementStatus) else status
            props["状态"] = {"select": {"name": s}}
        if keywords is not None:
            props["自动发现关键词"] = {"rich_text": _to_rich_text(keywords)}
        if research_url is not None:
            props["调研报告链接"] = {"url": research_url or None}
        if breakdown_url is not None:
            props["需求拆解链接"] = {"url": breakdown_url or None}
        if prd_url is not None:
            props["PRD链接"] = {"url": prd_url or None}
        if failure_reason is not None:
            props["失败原因"] = {"rich_text": _to_rich_text(failure_reason)}
        if req_id is not None:
            props["req_id"] = {"rich_text": _to_rich_text(req_id)}
        if not props:
            return
        self.sdk.pages.update(page_id=page_id, properties=props)

    # ----------------------- Skill Library -----------------------

    # 本项目使用的 10 字段子集（Notion column 名 → Skill 模型字段名）
    _SKILL_COLUMNS = {
        "Name": "name",
        "Skill Key": "skill_key",
        "Status": "status",
        "Version": "version",
        "Description": "description",
        "System Prompt": "system_prompt",
        "User Prompt Template": "user_prompt_template",
        "Input Variables": "input_variables",
        "Output Schema": "output_schema",
        "Model Preference": "model_preference",
        "适用管线": "pipeline",
    }

    def list_skills(self) -> list[Skill]:
        """查 Skill Library 全部行（按 10 字段子集解析）。"""
        all_rows: list[dict] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"database_id": self.settings.notion_db_skill_library}
            if cursor:
                params["start_cursor"] = cursor
            resp = self.sdk.databases.query(**params)
            all_rows.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return [self._row_to_skill(row) for row in all_rows]

    def _row_to_skill(self, row: dict) -> Skill:
        p = row["properties"]
        status_str = _select(p.get("Status", {})) or "Draft"
        try:
            status = SkillStatus(status_str)
        except ValueError:
            status = SkillStatus.DRAFT
        return Skill(
            page_id=row["id"],
            name=_title(p.get("Name", {})),
            skill_key=_rich_text(p.get("Skill Key", {})),
            status=status,
            version=_rich_text(p.get("Version", {})) or "0.1.0",
            description=_rich_text(p.get("Description", {})),
            system_prompt=_rich_text(p.get("System Prompt", {})),
            user_prompt_template=_rich_text(p.get("User Prompt Template", {})),
            input_variables=_rich_text(p.get("Input Variables", {})),
            output_schema=_rich_text(p.get("Output Schema", {})),
            model_preference=_select(p.get("Model Preference", {})) or "auto",
            pipeline=_multi_select(p.get("适用管线", {})),
        )

    def upsert_skill(self, skill: Skill) -> str:
        """按 skill_key 决定 create 还是 update；返回 page_id。

        只写 10 字段子集，Notion 上其他列不动以保持与原有用途兼容。
        """
        # 找现有：按 skill_key 精确匹配
        resp = self.sdk.databases.query(
            database_id=self.settings.notion_db_skill_library,
            filter={"property": "Skill Key", "rich_text": {"equals": skill.skill_key}},
            page_size=1,
        )
        existing = resp.get("results", [])
        props = self._skill_to_properties(skill)

        if existing:
            page_id = existing[0]["id"]
            self.sdk.pages.update(page_id=page_id, properties=props)
            logger.info("Skill 更新：%s (%s)", skill.skill_key, page_id)
            return page_id
        # 新建
        created = self.sdk.pages.create(
            parent={"database_id": self.settings.notion_db_skill_library},
            properties=props,
        )
        page_id = created["id"]
        logger.info("Skill 新建：%s (%s)", skill.skill_key, page_id)
        return page_id

    def _skill_to_properties(self, skill: Skill) -> dict[str, Any]:
        """Skill → Notion property 字典（仅 10 字段子集）。"""
        return {
            "Name": {"title": _to_title(skill.name)},
            "Skill Key": {"rich_text": _to_rich_text(skill.skill_key)},
            "Status": {"select": {"name": skill.status.value}},
            "Version": {"rich_text": _to_rich_text(skill.version)},
            "Description": {"rich_text": _to_rich_text(skill.description)},
            "System Prompt": {"rich_text": _to_rich_text(skill.system_prompt)},
            "User Prompt Template": {"rich_text": _to_rich_text(skill.user_prompt_template)},
            "Input Variables": {"rich_text": _to_rich_text(skill.input_variables)},
            "Output Schema": {"rich_text": _to_rich_text(skill.output_schema)},
            "Model Preference": {"select": {"name": skill.model_preference}},
            "适用管线": {
                "multi_select": [{"name": p} for p in skill.pipeline if p]
            },
        }
