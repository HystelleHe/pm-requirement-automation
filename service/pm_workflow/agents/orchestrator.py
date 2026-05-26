"""调研编排器 —— 包 Researcher + 状态机 + Notion 回写。

外部调用者（API / CLI）只跟这个入口打交道，不直接碰 Researcher / NotionClient 细节。

状态机（Phase 2 范围）：
  待处理 → 调研中  → 失败          （调研流程报错）
                  → "调研中" + research_url 填回   （成功，等 Phase 3 拆解 agent 接力）
"""

from __future__ import annotations

import logging
import traceback

from pm_workflow.agents.models import ResearchResult
from pm_workflow.agents.researcher import Researcher
from pm_workflow.config import Settings, get_settings
from pm_workflow.notion import NotionClient
from pm_workflow.notion.models import Requirement, RequirementStatus

logger = logging.getLogger(__name__)


def run_research_for_requirement(
    req: Requirement,
    *,
    notion: NotionClient | None = None,
    researcher: Researcher | None = None,
    settings: Settings | None = None,
    upload_to_notion: bool = True,
    max_competitors: int = 6,
) -> ResearchResult:
    """对单个需求跑完整调研流程，含 Notion 状态机 + research.md 上传。

    upload_to_notion=False 用于本地调试时不动 Notion。
    """
    settings = settings or get_settings()
    notion = notion or NotionClient(settings=settings)
    researcher = researcher or Researcher(settings=settings)

    # entry: 调研中
    try:
        notion.update_requirement(req.page_id, status=RequirementStatus.RESEARCHING)
    except Exception as e:
        logger.warning("置「调研中」状态失败（不阻塞，继续）：%s", e)

    try:
        result = researcher.research(req, max_competitors=max_competitors)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        logger.exception("调研流程崩溃：%s", msg)
        try:
            notion.update_requirement(
                req.page_id,
                status=RequirementStatus.FAILED,
                failure_reason=f"研究阶段失败：{msg}\n{traceback.format_exc()[:500]}",
            )
        except Exception as e2:
            logger.warning("置「失败」状态又失败：%s", e2)
        raise

    if not upload_to_notion:
        return result

    # success: 把 research.md 上传成需求行的子页面，回写 URL
    try:
        page_info = notion.create_subpage_with_markdown(
            parent_page_id=req.page_id,
            title=f"调研报告 - {req.name}",
            markdown=result.research_markdown,
        )
        notion.update_requirement(
            req.page_id,
            research_url=page_info["url"],
            req_id=result.req_id,  # 保证 Notion 行的 req_id 跟 outputs/ 目录一致
        )
        result.output_path = result.output_path  # 已落盘
        # status 保持「调研中」，等 Phase 3 拆解 agent 接力推进
    except Exception as e:
        msg = f"研究产出上传失败：{type(e).__name__}: {e}"
        logger.exception(msg)
        result.errors.append(msg)
        # 不抛 —— 文件已经落盘到 outputs/，Notion 上传失败是非致命的
        try:
            notion.update_requirement(
                req.page_id,
                failure_reason=msg,
            )
        except Exception as e2:
            logger.warning("失败原因写回 Notion 又失败：%s", e2)

    return result
