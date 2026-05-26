"""Notion 客户端 —— 用 httpx 直接调 Notion REST API（v2022-06-28）。

为什么不用 notion-client SDK：
- SDK 在 2.x 改成 data_sources 模型，需要 data_source_id 而不是 database_id，行为变动
- 我们 Phase 0 用 curl 验证的就是 v2022-06-28 协议，沿用最一致

提供：
- query_requirements(status) → 读需求表
- update_requirement(page_id, **fields) → 写状态/URL/失败原因
- list_skills() → 读 Skill Library 的 10 字段子集
- upsert_skill(skill) → 按 Skill Key 决定 create 还是 update（只写 10 列子集）
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from pm_workflow.config import Settings, get_settings
from pm_workflow.notion.markdown import markdown_to_notion_blocks
from pm_workflow.notion.models import (
    Requirement,
    RequirementStatus,
    Skill,
    SkillStatus,
)

logger = logging.getLogger(__name__)

NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_API_VERSION = "2022-06-28"


# ===================================================================
# Notion property 解构 / 构造工具
# ===================================================================


def _title(prop: dict) -> str:
    return "".join(x.get("plain_text", "") for x in prop.get("title", [])).strip()


def _rich_text(prop: dict) -> str:
    return "".join(x.get("plain_text", "") for x in prop.get("rich_text", [])).strip()


def _select(prop: dict) -> str | None:
    val = prop.get("select")
    return val.get("name") if val else None


def _multi_select(prop: dict) -> list[str]:
    return [x.get("name", "") for x in prop.get("multi_select", []) if x.get("name")]


def _url(prop: dict) -> str | None:
    return prop.get("url")


def _to_rich_text(text: str) -> list[dict]:
    """字符串 → Notion rich_text 数组。空串返回空数组。"""
    return [{"type": "text", "text": {"content": text}}] if text else []


def _to_title(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": text}}]


# ===================================================================
# NotionClient 主类
# ===================================================================


class NotionClient:
    """业务侧统一入口；线程安全的同步 httpx client。"""

    def __init__(self, settings: Settings | None = None, timeout: float = 30.0):
        self.settings = settings or get_settings()
        if not self.settings.notion_api_key:
            raise RuntimeError("NOTION_API_KEY 未配置，无法初始化 NotionClient")
        self._http = httpx.Client(
            base_url=NOTION_BASE_URL,
            headers={
                "Authorization": f"Bearer {self.settings.notion_api_key}",
                "Notion-Version": NOTION_API_VERSION,
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> NotionClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ----------------------- 通用 HTTP 操作 -----------------------

    def _post(self, path: str, json: dict) -> dict:
        resp = self._http.post(path, json=json)
        resp.raise_for_status()
        return resp.json()

    def _patch(self, path: str, json: dict) -> dict:
        resp = self._http.patch(path, json=json)
        resp.raise_for_status()
        return resp.json()

    def _query_db(self, database_id: str, body: dict | None = None) -> dict:
        """POST /v1/databases/{id}/query 抹平 v2022-06-28 协议细节。"""
        return self._post(f"/databases/{database_id}/query", json=body or {})

    # ----------------------- 需求表 -----------------------

    def query_requirements(
        self,
        status: RequirementStatus | str | None = RequirementStatus.PENDING,
    ) -> list[Requirement]:
        body: dict[str, Any] = {}
        if status is not None:
            status_str = status.value if isinstance(status, RequirementStatus) else status
            body["filter"] = {"property": "状态", "select": {"equals": status_str}}
        resp = self._query_db(self.settings.notion_db_requirements, body)
        return [self._row_to_requirement(r) for r in resp.get("results", [])]

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
        """部分更新需求表行；传 None 的字段保持不变。"""
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
        self._patch(f"/pages/{page_id}", json={"properties": props})

    # ----------------------- Skill Library -----------------------

    def list_skills(self) -> list[Skill]:
        """全量拉 Skill Library（自动分页）。"""
        all_rows: list[dict] = []
        body: dict[str, Any] = {}
        while True:
            resp = self._query_db(self.settings.notion_db_skill_library, body)
            all_rows.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            body = {"start_cursor": resp.get("next_cursor")}
        return [self._row_to_skill(r) for r in all_rows]

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

        只写 10 字段子集，Skill Library 其它列保持原值不动。
        """
        # 找现有：按 skill_key 精确匹配
        resp = self._query_db(
            self.settings.notion_db_skill_library,
            {
                "filter": {"property": "Skill Key", "rich_text": {"equals": skill.skill_key}},
                "page_size": 1,
            },
        )
        existing = resp.get("results", [])
        props = self._skill_to_properties(skill)

        if existing:
            page_id = existing[0]["id"]
            self._patch(f"/pages/{page_id}", json={"properties": props})
            logger.info("Skill 更新：%s (%s)", skill.skill_key, page_id)
            return page_id
        # 新建
        created = self._post(
            "/pages",
            json={
                "parent": {"database_id": self.settings.notion_db_skill_library},
                "properties": props,
            },
        )
        page_id = created["id"]
        logger.info("Skill 新建：%s (%s)", skill.skill_key, page_id)
        return page_id

    def _skill_to_properties(self, skill: Skill) -> dict[str, Any]:
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
            "适用管线": {"multi_select": [{"name": p} for p in skill.pipeline if p]},
        }

    # ----------------------- 通用：创建带 markdown 内容的子页面 -----------------------

    def create_subpage_with_markdown(
        self,
        *,
        parent_page_id: str,
        title: str,
        markdown: str,
    ) -> dict[str, str]:
        """在 parent_page_id 下建一个普通 page，正文是 markdown 转的 Notion blocks。

        返回 {'page_id': ..., 'url': ...}。

        Notion pages.create 单次 children 上限 100 块；如果 markdown 转出来超过，
        会先建空页再 append_children 分批。
        """
        all_blocks = markdown_to_notion_blocks(markdown)

        first_batch = all_blocks[:100]
        rest_batches = [all_blocks[i : i + 100] for i in range(100, len(all_blocks), 100)]

        body = {
            "parent": {"page_id": parent_page_id},
            "properties": {"title": [{"type": "text", "text": {"content": title}}]},
            "children": first_batch,
        }
        created = self._post("/pages", json=body)
        page_id = created["id"]
        url = created.get("url", "")
        logger.info("子页面创建：%s (parent=%s, 共 %d blocks)", page_id, parent_page_id, len(all_blocks))

        # 追加剩余 blocks
        for batch in rest_batches:
            self._patch(f"/blocks/{page_id}/children", json={"children": batch})

        return {"page_id": page_id, "url": url}

    # ----------------------- 调研结果缓存库 -----------------------

    def upsert_research_cache_entry(
        self,
        *,
        competitor: str,
        cache_url: str,
        source: str = "公开网页",
        req_id: str = "",
    ) -> str:
        """在 调研结果缓存 库中按 竞品名称 upsert 一行。返回 page_id。"""
        existing_resp = self._query_db(
            self.settings.notion_db_research_cache,
            {
                "filter": {"property": "竞品名称", "title": {"equals": competitor}},
                "page_size": 1,
            },
        )
        from datetime import datetime, timezone

        props: dict[str, Any] = {
            "竞品名称": {"title": _to_title(competitor)},
            "最后调研时间": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
            "缓存数据链接": {"url": cache_url or None},
            "来源": {"select": {"name": source}},
            "req_id": {"rich_text": _to_rich_text(req_id)},
        }
        existing = existing_resp.get("results", [])
        if existing:
            pid = existing[0]["id"]
            self._patch(f"/pages/{pid}", json={"properties": props})
            return pid
        created = self._post(
            "/pages",
            json={
                "parent": {"database_id": self.settings.notion_db_research_cache},
                "properties": props,
            },
        )
        return created["id"]
