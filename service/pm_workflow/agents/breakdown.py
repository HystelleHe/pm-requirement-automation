"""需求拆解 Agent —— 读 research.md → LLM 拆解 → 用户故事 JSON + breakdown.md。

数据流：
- 输入：Requirement（含 req_id）+ research_markdown（默认从 outputs/{req_id}/research.md 读）
- 中间：LLM 返回结构化 user_stories JSON
- 输出：渲染为 breakdown.md 落盘 + BreakdownResult 给上层
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pm_workflow.agents.models import (
    BreakdownResult,
    Priority,
    UserStory,
)
from pm_workflow.config import Settings, get_settings
from pm_workflow.llm import LLMRouter, LLMTask, SkillLoader
from pm_workflow.llm.parsing import parse_json_from_text
from pm_workflow.notion.models import Requirement

logger = logging.getLogger(__name__)


# ===================================================================
# user_stories JSON → breakdown.md 渲染
# ===================================================================


def render_breakdown_markdown(
    req_name: str,
    stories: list[UserStory],
    out_of_scope: list[str],
    open_questions: list[str],
) -> str:
    """把结构化拆解结果渲染成可读的 markdown。"""

    lines: list[str] = [f"# {req_name} - 需求拆解\n"]

    # 用户故事按 priority 分组（P0 > P1 > P2），同 priority 内保留顺序
    order: dict[Priority, list[UserStory]] = {"P0": [], "P1": [], "P2": []}
    for s in stories:
        order.setdefault(s.priority, []).append(s)

    if stories:
        lines.append("## 用户故事")
        for prio in ("P0", "P1", "P2"):
            bucket = order.get(prio, [])
            if not bucket:
                continue
            lines.append(f"\n### {prio}（{len(bucket)} 条）")
            for i, s in enumerate(bucket, 1):
                lines.append(f"\n**{prio}-{i}**：{s.story}")
                if s.rationale:
                    lines.append(f"\n_理由_：{s.rationale}")
                if s.acceptance_criteria:
                    lines.append("\n_验收标准_：")
                    for ac in s.acceptance_criteria:
                        lines.append(f"- {ac}")

    if out_of_scope:
        lines.append("\n## 明确不做（Out of Scope）")
        for x in out_of_scope:
            lines.append(f"- {x}")

    if open_questions:
        lines.append("\n## 开放问题（需要业务方决策）")
        for x in open_questions:
            lines.append(f"- {x}")

    return "\n".join(lines) + "\n"


# ===================================================================
# BreakdownAgent
# ===================================================================


class BreakdownAgent:
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

    def _parse_stories(self, raw: dict[str, Any], errors: list[str]) -> tuple[
        list[UserStory], list[str], list[str]
    ]:
        """容错地从 LLM 返回的 JSON 抠用户故事 + out_of_scope + open_questions。"""
        stories: list[UserStory] = []
        out_of_scope: list[str] = []
        open_questions: list[str] = []

        if not isinstance(raw, dict):
            errors.append(f"LLM 返回不是 dict：{type(raw).__name__}")
            return stories, out_of_scope, open_questions

        raw_stories = raw.get("user_stories") or []
        if not isinstance(raw_stories, list):
            errors.append(f"user_stories 不是 list：{type(raw_stories).__name__}")
            raw_stories = []

        for i, item in enumerate(raw_stories):
            if not isinstance(item, dict):
                errors.append(f"user_stories[{i}] 不是 dict，跳过")
                continue
            prio = str(item.get("priority", "P1")).upper()
            if prio not in ("P0", "P1", "P2"):
                errors.append(f"user_stories[{i}].priority={prio!r} 非法，落到 P1")
                prio = "P1"
            ac = item.get("acceptance_criteria") or []
            if not isinstance(ac, list):
                ac = [str(ac)]
            try:
                stories.append(
                    UserStory(
                        story=str(item.get("story", "")).strip(),
                        priority=prio,  # type: ignore[arg-type]
                        rationale=str(item.get("rationale", "")).strip(),
                        acceptance_criteria=[str(x).strip() for x in ac if str(x).strip()],
                    )
                )
            except Exception as e:
                errors.append(f"user_stories[{i}] 解析失败：{e}")

        for x in raw.get("out_of_scope") or []:
            s = str(x).strip()
            if s:
                out_of_scope.append(s)
        for x in raw.get("open_questions") or []:
            s = str(x).strip()
            if s:
                open_questions.append(s)

        return stories, out_of_scope, open_questions

    def breakdown(
        self,
        req: Requirement,
        *,
        research_markdown: str | None = None,
        req_id: str | None = None,
    ) -> BreakdownResult:
        """对单个需求跑拆解。

        参数:
          research_markdown: 上游 research.md 内容；不传则按 req_id 从 outputs/ 读
          req_id: outputs/{req_id}/ 目录名；不传用 req.req_id；都没有时用 page_id 截断
        """
        errors: list[str] = []
        rid = req_id or req.req_id or f"req-{req.page_id[:8]}"

        if research_markdown is None:
            try:
                research_markdown = self._load_research_markdown(rid)
            except FileNotFoundError as e:
                logger.exception("拆解阶段缺少上游 research.md")
                raise

        # 1. 渲染 prompt
        system, user = self.skills.render(
            "requirement_breakdown",
            requirement_name=req.name,
            scenario=req.scenario,
            research_markdown=research_markdown,
        )

        # 2. LLM 拆解
        resp = self.llm.chat(
            LLMTask.BREAKDOWN,
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

        stories, out_of_scope, open_questions = self._parse_stories(raw, errors)

        if not stories:
            errors.append("最终没有可用的用户故事")

        # 4. 渲染 markdown
        markdown = render_breakdown_markdown(req.name, stories, out_of_scope, open_questions)

        # 5. 落盘
        out_dir = self.settings.outputs_dir / rid
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "breakdown.md"
        out_path.write_text(markdown, "utf-8")

        # 原始数据备份
        raw_path = out_dir / "breakdown_raw.json"
        raw_path.write_text(
            json.dumps(
                {
                    "requirement": req.model_dump(mode="json"),
                    "user_stories": [s.model_dump(mode="json") for s in stories],
                    "out_of_scope": out_of_scope,
                    "open_questions": open_questions,
                    "llm_usage": resp.usage,
                    "errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            "utf-8",
        )

        return BreakdownResult(
            req_id=rid,
            req_page_id=req.page_id,
            requirement_name=req.name,
            user_stories=stories,
            out_of_scope=out_of_scope,
            open_questions=open_questions,
            breakdown_markdown=markdown,
            output_path=str(out_path),
            llm_usage=resp.usage,
            errors=errors,
        )
