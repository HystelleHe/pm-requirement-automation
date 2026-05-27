"""Insight Memo Agent —— Discover 路径终端：读 research.md → LLM → Insight Memo JSON + insight_memo.md。

数据流（对照 BreakdownAgent，结构刻意保持一致）：
- 输入：Requirement（含 req_id）+ research_markdown（默认从 outputs/{req_id}/research.md 读）
- 中间：LLM 返回结构化 JSON（key_insights / trends / opportunities / risks / open_questions）
- 输出：渲染为 insight_memo.md 落盘 + InsightMemoResult 给上层

与 BreakdownAgent 的差异：
- 用 LLMTask.INSIGHT_MEMO + skill_key="insight_memo"
- 输出结构不是 user_stories，而是洞察备忘录五段式
- 不接 critic 修订循环（先简）
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pm_workflow.agents.models import (
    InsightMemoResult,
    KeyInsight,
    Opportunity,
)
from pm_workflow.config import Settings, get_settings
from pm_workflow.llm import LLMRouter, LLMTask, SkillLoader
from pm_workflow.llm.parsing import parse_json_from_text
from pm_workflow.notion.models import Requirement

logger = logging.getLogger(__name__)


# ===================================================================
# JSON → insight_memo.md 渲染
# ===================================================================


def render_insight_memo_markdown(
    req_name: str,
    key_insights: list[KeyInsight],
    trends: list[str],
    opportunities: list[Opportunity],
    risks: list[str],
    open_questions: list[str],
) -> str:
    """把结构化 Insight Memo 渲染成可读的 markdown。"""
    lines: list[str] = [f"# {req_name} - 洞察备忘录\n"]

    if key_insights:
        lines.append("## 核心洞察")
        for i, ins in enumerate(key_insights, 1):
            lines.append(f"\n**洞察 {i}：{ins.title}**")
            if ins.evidence:
                lines.append(f"\n_证据_：{ins.evidence}")
            if ins.so_what:
                lines.append(f"\n_这意味着_：{ins.so_what}")

    if trends:
        lines.append("\n## 趋势线")
        for t in trends:
            lines.append(f"- {t}")

    if opportunities:
        lines.append("\n## 机会点")
        for i, op in enumerate(opportunities, 1):
            lines.append(f"\n**机会 {i}：{op.title}**")
            if op.rationale:
                lines.append(f"\n_理由_：{op.rationale}")

    if risks:
        lines.append("\n## 风险与挑战")
        for r in risks:
            lines.append(f"- {r}")

    if open_questions:
        lines.append("\n## 开放问题（需继续调研）")
        for q in open_questions:
            lines.append(f"- {q}")

    return "\n".join(lines) + "\n"


# ===================================================================
# InsightMemoAgent
# ===================================================================


class InsightMemoAgent:
    def __init__(
        self,
        *,
        llm: LLMRouter | None = None,
        skills: SkillLoader | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.llm = llm or LLMRouter(settings=self.settings)
        self.skills = skills or SkillLoader(settings=self.settings)

    def _load_research_markdown(self, req_id: str) -> str:
        """从 outputs/{req_id}/research.md 读上游调研结果。不存在则抛 FileNotFoundError。"""
        p: Path = self.settings.outputs_dir / req_id / "research.md"
        if not p.exists():
            raise FileNotFoundError(
                f"找不到上游调研结果：{p}。请先跑 research 阶段产出 research.md"
            )
        return p.read_text("utf-8")

    def _parse(
        self, raw: dict[str, Any], errors: list[str]
    ) -> tuple[list[KeyInsight], list[str], list[Opportunity], list[str], list[str]]:
        """容错地从 LLM 返回的 JSON 抠出五段内容。"""
        key_insights: list[KeyInsight] = []
        trends: list[str] = []
        opportunities: list[Opportunity] = []
        risks: list[str] = []
        open_questions: list[str] = []

        if not isinstance(raw, dict):
            errors.append(f"LLM 返回不是 dict：{type(raw).__name__}")
            return key_insights, trends, opportunities, risks, open_questions

        # key_insights：三段式
        for i, item in enumerate(raw.get("key_insights") or []):
            if not isinstance(item, dict):
                errors.append(f"key_insights[{i}] 不是 dict，跳过")
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                errors.append(f"key_insights[{i}] title 为空，跳过")
                continue
            try:
                key_insights.append(
                    KeyInsight(
                        title=title,
                        evidence=str(item.get("evidence", "")).strip(),
                        so_what=str(item.get("so_what", "")).strip(),
                    )
                )
            except Exception as e:
                errors.append(f"key_insights[{i}] 解析失败：{e}")

        # opportunities：title + rationale
        for i, item in enumerate(raw.get("opportunities") or []):
            if not isinstance(item, dict):
                errors.append(f"opportunities[{i}] 不是 dict，跳过")
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            try:
                opportunities.append(
                    Opportunity(
                        title=title,
                        rationale=str(item.get("rationale", "")).strip(),
                    )
                )
            except Exception as e:
                errors.append(f"opportunities[{i}] 解析失败：{e}")

        # trends / risks / open_questions：纯字符串列表
        for key, target in (
            ("trends", trends),
            ("risks", risks),
            ("open_questions", open_questions),
        ):
            for x in raw.get(key) or []:
                s = str(x).strip()
                if s:
                    target.append(s)

        return key_insights, trends, opportunities, risks, open_questions

    def generate(
        self,
        req: Requirement,
        *,
        research_markdown: str | None = None,
        req_id: str | None = None,
    ) -> InsightMemoResult:
        """对单个 Discover 需求生成 Insight Memo。

        参数与 BreakdownAgent.breakdown 同形，便于 orchestrator 统一调用。
        """
        errors: list[str] = []
        rid = req_id or req.req_id or f"req-{req.page_id[:8]}"

        if research_markdown is None:
            research_markdown = self._load_research_markdown(rid)

        # 1. 渲染 prompt
        system, user = self.skills.render(
            "insight_memo",
            requirement_name=req.name,
            scenario=req.scenario,
            research_markdown=research_markdown,
        )

        # 2. LLM 生成
        resp = self.llm.chat(
            LLMTask.INSIGHT_MEMO,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
        )

        # 3. 解析 JSON
        try:
            raw = parse_json_from_text(resp.content)
        except ValueError as e:
            err = f"LLM 返回无法解析为 JSON：{e}（content preview: {resp.content[:200]!r}）"
            logger.error(err)
            errors.append(err)
            raw = {}

        key_insights, trends, opportunities, risks, open_questions = self._parse(raw, errors)

        if not key_insights:
            errors.append("最终没有可用的核心洞察")

        # 4. 渲染 markdown
        markdown = render_insight_memo_markdown(
            req.name, key_insights, trends, opportunities, risks, open_questions
        )

        # 5. 落盘
        out_dir = self.settings.outputs_dir / rid
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "insight_memo.md"
        out_path.write_text(markdown, "utf-8")

        # 原始数据备份
        raw_path = out_dir / "insight_memo_raw.json"
        raw_path.write_text(
            json.dumps(
                {
                    "requirement": req.model_dump(mode="json"),
                    "key_insights": [k.model_dump(mode="json") for k in key_insights],
                    "trends": trends,
                    "opportunities": [o.model_dump(mode="json") for o in opportunities],
                    "risks": risks,
                    "open_questions": open_questions,
                    "llm_usage": resp.usage,
                    "errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            "utf-8",
        )

        return InsightMemoResult(
            req_id=rid,
            req_page_id=req.page_id,
            requirement_name=req.name,
            key_insights=key_insights,
            trends=trends,
            opportunities=opportunities,
            risks=risks,
            open_questions=open_questions,
            insight_markdown=markdown,
            output_path=str(out_path),
            llm_usage=resp.usage,
            errors=errors,
        )
