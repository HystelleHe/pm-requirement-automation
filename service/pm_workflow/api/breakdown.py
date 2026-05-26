"""拆解阶段的 HTTP 路由。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pm_workflow.agents.orchestrator import run_breakdown_for_requirement
from pm_workflow.notion import NotionClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/breakdown", tags=["breakdown"])


class BreakdownRequest(BaseModel):
    req_page_id: str = Field(..., description="需求表行的 Notion page UUID")
    upload_to_notion: bool = Field(default=True)


class BreakdownResponse(BaseModel):
    req_id: str
    breakdown_url: str | None = None
    story_count: int
    output_path: str
    llm_total_tokens: int = 0
    errors: list[str] = Field(default_factory=list)


@router.post("", response_model=BreakdownResponse)
def trigger_breakdown(payload: BreakdownRequest) -> BreakdownResponse:
    """同步执行拆解（30-60 秒阻塞）。

    前置条件：outputs/{req_id}/research.md 必须存在（即先跑过 /research）。
    """
    notion = NotionClient()
    all_reqs = notion.query_requirements(status=None)
    target = next((r for r in all_reqs if r.page_id == payload.req_page_id), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"需求行未找到: {payload.req_page_id}")

    try:
        result = run_breakdown_for_requirement(
            target,
            notion=notion,
            upload_to_notion=payload.upload_to_notion,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=409, detail=str(e))  # 409 表前置依赖未满足

    breakdown_url: str | None = None
    if payload.upload_to_notion:
        refreshed = next(
            (r for r in notion.query_requirements(status=None) if r.page_id == target.page_id),
            None,
        )
        if refreshed:
            breakdown_url = refreshed.breakdown_url

    return BreakdownResponse(
        req_id=result.req_id,
        breakdown_url=breakdown_url,
        story_count=len(result.user_stories),
        output_path=result.output_path,
        llm_total_tokens=result.llm_usage.get("total_tokens", 0),
        errors=result.errors,
    )
