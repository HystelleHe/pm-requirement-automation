"""FastAPI 应用入口（占位）。

Phase 1 只起 /health 端点确保容器健康，业务路由 Phase 2-4 逐步补齐。
"""

from fastapi import FastAPI

from pm_workflow import __version__
from pm_workflow.config import get_settings

app = FastAPI(
    title="PM 需求自动化 - 能力层",
    description="Notion 触发 → 竞品调研 + 需求拆解 + PRD 撰写",
    version=__version__,
)


@app.get("/health")
def health():
    """容器健康检查端点，验证服务进程存活 + 配置可读。"""
    s = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "llm_gateway_url": s.llm_gateway_url,
        "notion_configured": bool(s.notion_api_key and s.notion_db_requirements),
    }
