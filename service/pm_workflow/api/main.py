"""FastAPI 应用入口。

Phase 1 提供：
- /health：容器健康检查 + 配置就绪度
- /skills/sync：手动触发 Skill Library 同步
- /skills/search：列出 active skills（按管线筛选）

Phase 2-4 在 agents/ 下补 researcher/breakdown/prd_writer 后，
在这里注册对应的 POST 路由。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query

from pm_workflow import __version__
from pm_workflow.agents.skill_sync import SkillSyncer
from pm_workflow.api.research import router as research_router
from pm_workflow.config import get_settings
from pm_workflow.notion import NotionClient, SkillStatus

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时同步 Skill Library，关闭时清理。

    skill sync 失败不阻止启动 —— 业务路径不强依赖 sync 成功（agents 直接读 Notion）。
    """
    logger.info("service 启动：开始同步 skill-library/ → Notion")
    try:
        results = SkillSyncer().sync()
        logger.info("Skill sync 结果：%s", results)
    except Exception as e:
        logger.warning("Skill sync 失败（不阻止启动）：%s", e)
    yield
    logger.info("service 关闭")


app = FastAPI(
    title="PM 需求自动化 - 能力层",
    description="Notion 触发 → 竞品调研 + 需求拆解 + PRD 撰写",
    version=__version__,
    lifespan=lifespan,
)

# 各 phase 的业务路由
app.include_router(research_router)


@app.get("/health")
def health() -> dict[str, Any]:
    """容器健康检查 + 配置就绪度。"""
    s = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "llm_gateway_configured": bool(s.llm_gateway_token),
        "notion_configured": bool(s.notion_api_key and s.notion_db_requirements),
        "tavily_configured": bool(s.tavily_api_key),
        "langfuse_traced": bool(s.langfuse_public_key and s.langfuse_secret_key),
    }


@app.post("/skills/sync")
def sync_skills() -> dict[str, str]:
    """手动触发 Skill Library 同步（不重启服务也能拉本地最新 prompt）。"""
    return SkillSyncer().sync()


@app.get("/skills/search")
def search_skills(
    pipeline: str | None = Query(default=None, description="按适用管线过滤，如 竞品调研/PRD/Figma"),
    active_only: bool = Query(default=True, description="是否只返回 Active 状态"),
) -> list[dict[str, Any]]:
    """列出 Skill Library 中的 skill。"""
    notion = NotionClient()
    skills = notion.list_skills()
    if active_only:
        skills = [s for s in skills if s.status == SkillStatus.ACTIVE]
    if pipeline:
        skills = [s for s in skills if pipeline in s.pipeline]
    return [s.model_dump(mode="json") for s in skills]
