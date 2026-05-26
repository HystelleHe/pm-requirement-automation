"""三 stage 编排器 —— 包 Researcher / BreakdownAgent / PRDAgent + 状态机 + Notion 回写 + 飞书通知。

外部调用者（API / CLI / n8n）只跟这些入口打交道，不直接碰 agent / NotionClient / Notifier 细节。

状态机（Phase 2-4 全部）：
  待处理 → 调研中 → 拆解中 → PRD生成中 → 已完成
  任何 stage 报错 → 失败（写 failure_reason）
"""

from __future__ import annotations

import logging
import traceback

from pm_workflow.agents.breakdown import BreakdownAgent
from pm_workflow.agents.models import BreakdownResult, PRDResult, ResearchResult
from pm_workflow.agents.prd_writer import PRDAgent
from pm_workflow.agents.researcher import Researcher
from pm_workflow.config import Settings, get_settings
from pm_workflow.notion import NotionClient
from pm_workflow.notion.models import Requirement, RequirementStatus
from pm_workflow.notifier import Notifier, StageEvent

logger = logging.getLogger(__name__)


def _notify(notifier: Notifier | None, event: StageEvent) -> None:
    """统一通知入口；任何异常都吞掉不阻塞主流程。

    Notifier.send_stage 内部已经吞异常，这层再包一层是为了 notifier 自身初始化也可能挂。
    """
    if notifier is None:
        return
    try:
        notifier.send_stage(event)
    except Exception as e:
        logger.warning("通知发送失败（不阻塞主流程）：%s: %s", type(e).__name__, e)


def run_research_for_requirement(
    req: Requirement,
    *,
    notion: NotionClient | None = None,
    researcher: Researcher | None = None,
    notifier: Notifier | None = None,
    settings: Settings | None = None,
    upload_to_notion: bool = True,
    max_competitors: int = 6,
) -> ResearchResult:
    """对单个需求跑完整调研流程，含 Notion 状态机 + research.md 上传 + 飞书通知。

    upload_to_notion=False 用于本地调试时不动 Notion。
    """
    settings = settings or get_settings()
    notion = notion or NotionClient(settings=settings)
    researcher = researcher or Researcher(settings=settings)
    notifier = notifier or Notifier(settings=settings)

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
        _notify(
            notifier,
            StageEvent(
                stage="research",
                outcome="failure",
                requirement_name=req.name,
                req_id=req.req_id or f"req-{req.page_id[:8]}",
                failure_reason=msg,
            ),
        )
        raise

    if not upload_to_notion:
        _notify(
            notifier,
            StageEvent(
                stage="research",
                outcome="success",
                requirement_name=req.name,
                req_id=result.req_id,
                summary=f"{len(result.competitors)} 竞品，{result.llm_usage.get('total_tokens', 0)} tokens（本地模式，未上传 Notion）",
            ),
        )
        return result

    # success: 把 research.md 上传成需求行的子页面，回写 URL
    detail_url = ""
    try:
        page_info = notion.create_subpage_with_markdown(
            parent_page_id=req.page_id,
            title=f"调研报告 - {req.name}",
            markdown=result.research_markdown,
        )
        detail_url = page_info["url"]
        notion.update_requirement(
            req.page_id,
            research_url=detail_url,
            req_id=result.req_id,  # 保证 Notion 行的 req_id 跟 outputs/ 目录一致
        )
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

    _notify(
        notifier,
        StageEvent(
            stage="research",
            outcome="success",
            requirement_name=req.name,
            req_id=result.req_id,
            summary=f"{len(result.competitors)} 竞品，{result.llm_usage.get('total_tokens', 0)} tokens",
            detail_url=detail_url,
        ),
    )
    return result


def run_breakdown_for_requirement(
    req: Requirement,
    *,
    notion: NotionClient | None = None,
    agent: BreakdownAgent | None = None,
    notifier: Notifier | None = None,
    settings: Settings | None = None,
    upload_to_notion: bool = True,
    research_markdown: str | None = None,
) -> BreakdownResult:
    """对单个需求跑拆解流程，含状态机 + Notion 回写 + 飞书通知。

    状态机:
      entry: 调研中（或任意） → 拆解中
      success: breakdown.md 上传成子页面 + 回写需求表「需求拆解链接」
               status 保持「拆解中」，等 Phase 4 PRD agent 接力
      fail: 状态置「失败」 + failure_reason 写回
    """
    settings = settings or get_settings()
    notion = notion or NotionClient(settings=settings)
    agent = agent or BreakdownAgent(settings=settings)
    notifier = notifier or Notifier(settings=settings)
    rid = req.req_id or f"req-{req.page_id[:8]}"

    try:
        notion.update_requirement(req.page_id, status=RequirementStatus.BREAKING_DOWN)
    except Exception as e:
        logger.warning("置「拆解中」状态失败（不阻塞，继续）：%s", e)

    try:
        result = agent.breakdown(req, research_markdown=research_markdown)
    except FileNotFoundError as e:
        # 上游 research.md 缺失 —— 这是预期内的失败情况，给出更友好的错误信息
        msg = f"拆解前置依赖缺失：{e}"
        logger.error(msg)
        try:
            notion.update_requirement(
                req.page_id, status=RequirementStatus.FAILED, failure_reason=msg
            )
        except Exception as e2:
            logger.warning("置「失败」状态又失败：%s", e2)
        _notify(
            notifier,
            StageEvent(
                stage="breakdown",
                outcome="failure",
                requirement_name=req.name,
                req_id=rid,
                failure_reason=msg,
            ),
        )
        raise
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        logger.exception("拆解流程崩溃：%s", msg)
        try:
            notion.update_requirement(
                req.page_id, status=RequirementStatus.FAILED, failure_reason=msg
            )
        except Exception as e2:
            logger.warning("置「失败」状态又失败：%s", e2)
        _notify(
            notifier,
            StageEvent(
                stage="breakdown",
                outcome="failure",
                requirement_name=req.name,
                req_id=rid,
                failure_reason=msg,
            ),
        )
        raise

    summary = (
        f"{len(result.user_stories)} 用户故事，"
        f"{result.llm_usage.get('total_tokens', 0)} tokens"
    )

    if not upload_to_notion:
        _notify(
            notifier,
            StageEvent(
                stage="breakdown",
                outcome="success",
                requirement_name=req.name,
                req_id=result.req_id,
                summary=summary + "（本地模式，未上传 Notion）",
            ),
        )
        return result

    # 上传 breakdown.md 作为子页面 + 回写 URL
    detail_url = ""
    try:
        page_info = notion.create_subpage_with_markdown(
            parent_page_id=req.page_id,
            title=f"需求拆解 - {req.name}",
            markdown=result.breakdown_markdown,
        )
        detail_url = page_info["url"]
        notion.update_requirement(
            req.page_id,
            breakdown_url=detail_url,
        )
    except Exception as e:
        msg = f"拆解产出上传失败：{type(e).__name__}: {e}"
        logger.exception(msg)
        result.errors.append(msg)
        try:
            notion.update_requirement(req.page_id, failure_reason=msg)
        except Exception as e2:
            logger.warning("失败原因写回 Notion 又失败：%s", e2)

    _notify(
        notifier,
        StageEvent(
            stage="breakdown",
            outcome="success",
            requirement_name=req.name,
            req_id=result.req_id,
            summary=summary,
            detail_url=detail_url,
        ),
    )
    return result


def run_prd_for_requirement(
    req: Requirement,
    *,
    notion: NotionClient | None = None,
    agent: PRDAgent | None = None,
    notifier: Notifier | None = None,
    settings: Settings | None = None,
    upload_to_notion: bool = True,
    research_markdown: str | None = None,
    breakdown_markdown: str | None = None,
) -> PRDResult:
    """对单个需求跑 PRD 生成 + Critic 修订循环，含状态机 + Notion 回写 + 飞书通知。

    状态机:
      entry: 拆解中（或任意） → PRD生成中
      success: prd.md 上传成子页面 + 回写需求表「PRD链接」 + 状态置「已完成」
      fail: 状态置「失败」 + failure_reason 写回

    前置：outputs/{req_id}/research.md + breakdown.md 必须存在（先跑过前两阶段）
    """
    settings = settings or get_settings()
    notion = notion or NotionClient(settings=settings)
    agent = agent or PRDAgent(settings=settings)
    notifier = notifier or Notifier(settings=settings)
    rid = req.req_id or f"req-{req.page_id[:8]}"

    try:
        notion.update_requirement(req.page_id, status=RequirementStatus.WRITING_PRD)
    except Exception as e:
        logger.warning("置「PRD生成中」状态失败（不阻塞，继续）：%s", e)

    try:
        result = agent.generate(
            req,
            research_markdown=research_markdown,
            breakdown_markdown=breakdown_markdown,
        )
    except FileNotFoundError as e:
        # 上游 research.md 或 breakdown.md 缺失
        msg = f"PRD 前置依赖缺失：{e}"
        logger.error(msg)
        try:
            notion.update_requirement(
                req.page_id, status=RequirementStatus.FAILED, failure_reason=msg
            )
        except Exception as e2:
            logger.warning("置「失败」状态又失败：%s", e2)
        _notify(
            notifier,
            StageEvent(
                stage="prd",
                outcome="failure",
                requirement_name=req.name,
                req_id=rid,
                failure_reason=msg,
            ),
        )
        raise
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        logger.exception("PRD 生成崩溃：%s", msg)
        try:
            notion.update_requirement(
                req.page_id, status=RequirementStatus.FAILED, failure_reason=msg
            )
        except Exception as e2:
            logger.warning("置「失败」状态又失败：%s", e2)
        _notify(
            notifier,
            StageEvent(
                stage="prd",
                outcome="failure",
                requirement_name=req.name,
                req_id=rid,
                failure_reason=msg,
            ),
        )
        raise

    summary = (
        f"修订 {result.revisions} 次，"
        f"最终分 {result.reviews[-1].overall_score if result.reviews else 'N/A'}，"
        f"{result.llm_usage.get('total_tokens', 0)} tokens"
    )

    if not upload_to_notion:
        _notify(
            notifier,
            StageEvent(
                stage="prd",
                outcome="success",
                requirement_name=req.name,
                req_id=result.req_id,
                summary=summary + "（本地模式，未上传 Notion）",
            ),
        )
        return result

    # 上传 prd.md 作为子页面 + 回写 URL + 状态置「已完成」
    detail_url = ""
    try:
        page_info = notion.create_subpage_with_markdown(
            parent_page_id=req.page_id,
            title=f"PRD - {req.name}",
            markdown=result.prd_markdown,
        )
        detail_url = page_info["url"]
        notion.update_requirement(
            req.page_id,
            prd_url=detail_url,
            status=RequirementStatus.DONE,
        )
    except Exception as e:
        msg = f"PRD 产出上传失败：{type(e).__name__}: {e}"
        logger.exception(msg)
        result.errors.append(msg)
        try:
            notion.update_requirement(req.page_id, failure_reason=msg)
        except Exception as e2:
            logger.warning("失败原因写回 Notion 又失败：%s", e2)

    _notify(
        notifier,
        StageEvent(
            stage="prd",
            outcome="success",
            requirement_name=req.name,
            req_id=result.req_id,
            summary=summary,
            detail_url=detail_url,
        ),
    )
    return result
