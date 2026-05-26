"""调研阶段的 HTTP 路由。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pm_workflow.agents.orchestrator import run_research_for_requirement
from pm_workflow.notion import NotionClient
from pm_workflow.notion.models import Requirement

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/research", tags=["research"])


class ResearchRequest(BaseModel):
    req_page_id: str = Field(..., description="需求表行的 Notion page UUID")
    max_competitors: int = Field(default=6, ge=1, le=20)
    upload_to_notion: bool = Field(default=True, description="False 仅本地落盘，不动 Notion")


class ResearchResponse(BaseModel):
    req_id: str
    research_url: str | None = None
    competitors_count: int
    output_path: str
    llm_total_tokens: int = 0
    errors: list[str] = Field(default_factory=list)


def _fetch_requirement(req_page_id: str, notion: NotionClient) -> Requirement:
    """从 Notion 取单个需求行 —— SDK 没有 by-id 查询接口，遍历库找。"""
    # query_requirements(status=None) 拉全部，再 in-memory 过滤
    all_reqs = notion.query_requirements(status=None)
    for r in all_reqs:
        if r.page_id == req_page_id:
            return r
    raise HTTPException(status_code=404, detail=f"需求行未找到: {req_page_id}")


@router.post("", response_model=ResearchResponse)
def trigger_research(payload: ResearchRequest) -> ResearchResponse:
    """同步执行调研（1-3 分钟阻塞）。

    生产场景应改 BackgroundTasks 异步 + polling 状态，MVP 阶段同步以简化调用。
    """
    notion = NotionClient()
    req = _fetch_requirement(payload.req_page_id, notion)
    logger.info("调研触发：%s (%s)", req.name, req.page_id[:13])

    result = run_research_for_requirement(
        req,
        notion=notion,
        upload_to_notion=payload.upload_to_notion,
        max_competitors=payload.max_competitors,
    )

    # 调研成功后从 Notion 再读一次 research_url
    research_url: str | None = None
    if payload.upload_to_notion:
        refreshed = _fetch_requirement(req.page_id, notion)
        research_url = refreshed.research_url

    return ResearchResponse(
        req_id=result.req_id,
        research_url=research_url,
        competitors_count=len(result.competitors),
        output_path=result.output_path,
        llm_total_tokens=result.llm_usage.get("total_tokens", 0),
        errors=result.errors,
    )
