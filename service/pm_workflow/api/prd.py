"""PRD 生成阶段的 HTTP 路由（Phase 4）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pm_workflow.agents.orchestrator import run_prd_for_requirement
from pm_workflow.notion import NotionClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/prd", tags=["prd"])


class PRDRequest(BaseModel):
    req_page_id: str = Field(..., description="需求表行的 Notion page UUID")
    upload_to_notion: bool = Field(default=True)


class CriticReviewSummary(BaseModel):
    round: int
    overall_score: int
    needs_revision: bool
    issue_count: int
    summary: str = ""


class PRDResponse(BaseModel):
    req_id: str
    prd_url: str | None = None
    revisions: int  # 实际触发了几次修订
    reviews: list[CriticReviewSummary]
    output_path: str
    llm_total_tokens: int = 0
    errors: list[str] = Field(default_factory=list)


@router.post("", response_model=PRDResponse)
def trigger_prd(payload: PRDRequest) -> PRDResponse:
    """同步执行 PRD 生成（含 Critic 修订循环；2-5 分钟阻塞）。

    前置：outputs/{req_id}/research.md + breakdown.md 必须存在
    """
    notion = NotionClient()
    all_reqs = notion.query_requirements(status=None)
    target = next((r for r in all_reqs if r.page_id == payload.req_page_id), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"需求行未找到: {payload.req_page_id}")

    try:
        result = run_prd_for_requirement(
            target,
            notion=notion,
            upload_to_notion=payload.upload_to_notion,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=409, detail=str(e))

    prd_url: str | None = None
    if payload.upload_to_notion:
        refreshed = next(
            (r for r in notion.query_requirements(status=None) if r.page_id == target.page_id),
            None,
        )
        if refreshed:
            prd_url = refreshed.prd_url

    reviews_summary = [
        CriticReviewSummary(
            round=r.round,
            overall_score=r.overall_score,
            needs_revision=r.needs_revision,
            issue_count=len(r.issues),
            summary=r.summary,
        )
        for r in result.reviews
    ]

    return PRDResponse(
        req_id=result.req_id,
        prd_url=prd_url,
        revisions=result.revisions,
        reviews=reviews_summary,
        output_path=result.output_path,
        llm_total_tokens=result.llm_usage.get("total_tokens", 0),
        errors=result.errors,
    )
