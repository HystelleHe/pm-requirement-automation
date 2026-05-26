"""调研 Agent —— 把场景转化成竞品调研报告。

流程：
1. competitor_discovery skill + Kimi 推断潜在竞品名单
2. 与用户指定竞品合并去重
3. 每个竞品用 Tavily 搜 "{name} 官网 产品介绍"，拿 answer + 前几条 results
4. research_synthesis skill + Kimi 整合成 research.md
5. 落盘到 outputs/{req_id}/research.md

未来扩展点（暂未做）：
- 用 Playwright 抓竞品官网正文做更深入摘要（增加 5-10× LLM 调用成本）
- 增加 Research_Cache 库查询（24h 内同竞品复用结果）
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from pm_workflow.agents.models import CompetitorSnapshot, ResearchResult
from pm_workflow.config import Settings, get_settings
from pm_workflow.llm import LLMRouter, LLMTask, SkillLoader
from pm_workflow.llm.parsing import parse_json_from_text
from pm_workflow.notion.models import Requirement
from pm_workflow.scrapers.tavily import TavilySearcher

logger = logging.getLogger(__name__)


class Researcher:
    def __init__(
        self,
        *,
        llm: LLMRouter | None = None,
        skills: SkillLoader | None = None,
        tavily: TavilySearcher | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.llm = llm or LLMRouter(settings=self.settings)
        self.skills = skills or SkillLoader(settings=self.settings)
        self.tavily = tavily or TavilySearcher(settings=self.settings)

    # ------------------------------------------------------------
    # Step 1: 列候选竞品
    # ------------------------------------------------------------

    def _discover_candidates(self, req: Requirement, errors: list[str]) -> list[dict[str, str]]:
        """让 Kimi 凭领域知识列 5-8 个潜在竞品。返回 [{name, reason, url_hint}]。"""
        system, user = self.skills.render(
            "competitor_discovery",
            scenario=req.scenario,
            specified_competitors=", ".join(req.competitors) if req.competitors else "无",
        )
        resp = self.llm.chat(
            LLMTask.KEYWORD_DISCOVERY,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        try:
            data = parse_json_from_text(resp.content)
            items = data.get("competitors", []) if isinstance(data, dict) else data
            if not isinstance(items, list):
                raise ValueError(f"unexpected JSON shape: {type(items).__name__}")
            return [
                {
                    "name": str(x.get("name", "")).strip(),
                    "reason": str(x.get("reason", "")).strip(),
                    "url_hint": str(x.get("url_hint", "")).strip(),
                }
                for x in items
                if isinstance(x, dict) and x.get("name")
            ]
        except (ValueError, KeyError, TypeError) as e:
            err = f"竞品候选解析失败：{e}（content preview: {resp.content[:200]!r}）"
            logger.warning(err)
            errors.append(err)
            return []

    # ------------------------------------------------------------
    # Step 2 + 3: Tavily 调研每个竞品
    # ------------------------------------------------------------

    def _research_each(
        self,
        competitors: list[CompetitorSnapshot],
        errors: list[str],
        max_results: int = 3,
    ) -> None:
        """对每个竞品跑一次 Tavily 搜索，结果挂回 snapshot.tavily_*。原地修改。"""
        for comp in competitors:
            query = f"{comp.name} 产品介绍 官网"
            try:
                tav = self.tavily.search(
                    query, max_results=max_results, include_answer=True
                )
                comp.tavily_answer = tav.answer
                comp.tavily_results = tav.results
            except Exception as e:
                err = f"Tavily 搜索 {comp.name!r} 失败：{e}"
                logger.warning(err)
                errors.append(err)

    # ------------------------------------------------------------
    # Step 4: 把竞品数据拼装成 LLM 友好的输入
    # ------------------------------------------------------------

    @staticmethod
    def _format_competitors_for_llm(competitors: list[CompetitorSnapshot]) -> str:
        chunks: list[str] = []
        for c in competitors:
            buf = [f"## 竞品：{c.name}"]
            buf.append(f"列入原因（{c.source}）：{c.reason or '(无)'}")
            if c.tavily_answer:
                buf.append(f"Tavily 总结：{c.tavily_answer}")
            if c.tavily_results:
                buf.append("搜索结果：")
                for r in c.tavily_results[:3]:
                    snippet = (r.content or "")[:500].replace("\n", " ")
                    buf.append(f"- [{r.title}]({r.url})\n  {snippet}")
            else:
                buf.append("搜索结果：(无)")
            chunks.append("\n".join(buf))
        return "\n\n".join(chunks)

    # ------------------------------------------------------------
    # Step 5: LLM 整合
    # ------------------------------------------------------------

    def _synthesize(
        self,
        req: Requirement,
        competitors: list[CompetitorSnapshot],
        errors: list[str],
    ) -> tuple[str, dict[str, Any]]:
        competitors_data = self._format_competitors_for_llm(competitors)
        system, user = self.skills.render(
            "research_synthesis",
            requirement_name=req.name,
            scenario=req.scenario,
            competitors_data=competitors_data,
        )
        try:
            resp = self.llm.chat(
                LLMTask.RESEARCH_SYNTHESIS,
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            return resp.content, resp.usage
        except Exception as e:
            err = f"调研整合 LLM 调用失败：{e}"
            logger.exception(err)
            errors.append(err)
            # 降级：拼一个最简单的报告
            fallback = (
                f"# {req.name} 调研报告\n\n"
                f"> 调研整合失败（{e}），下面只是原始数据集合。\n\n"
                f"{competitors_data}\n"
            )
            return fallback, {}

    # ------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------

    def research(self, req: Requirement, *, max_competitors: int = 8) -> ResearchResult:
        """对单个需求完整跑一次调研，返回结构化结果且 markdown 已落盘。"""
        errors: list[str] = []

        # 1. 让 LLM 列候选
        llm_candidates = self._discover_candidates(req, errors)

        # 2. 合并：user 指定优先，LLM 候选去重后补足到 max_competitors
        seen: set[str] = set()
        competitors: list[CompetitorSnapshot] = []
        for name in req.competitors:
            if name and name.lower() not in seen:
                competitors.append(CompetitorSnapshot(name=name, source="user"))
                seen.add(name.lower())
        for cand in llm_candidates:
            if len(competitors) >= max_competitors:
                break
            n = cand["name"]
            if n.lower() in seen:
                continue
            competitors.append(
                CompetitorSnapshot(name=n, reason=cand.get("reason", ""), source="llm")
            )
            seen.add(n.lower())

        if not competitors:
            errors.append("没有可调研的竞品（用户未指定 + LLM 也未给出）")
            logger.warning("竞品列表为空，提前结束")

        # 3. Tavily 搜每个
        self._research_each(competitors, errors)

        # 4. LLM 整合
        markdown, usage = self._synthesize(req, competitors, errors)

        # 5. 落盘
        req_id = req.req_id or f"req-{uuid.uuid4().hex[:8]}"
        out_dir = self.settings.outputs_dir / req_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "research.md"
        out_path.write_text(markdown, "utf-8")
        # 同时保存原始数据快照，便于事后审计 / 重跑
        raw_path = out_dir / "research_raw.json"
        raw_path.write_text(
            json.dumps(
                {
                    "requirement": req.model_dump(mode="json"),
                    "competitors": [c.model_dump(mode="json") for c in competitors],
                    "llm_usage": usage,
                    "errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            "utf-8",
        )

        return ResearchResult(
            req_id=req_id,
            req_page_id=req.page_id,
            requirement_name=req.name,
            scenario=req.scenario,
            competitors=competitors,
            research_markdown=markdown,
            output_path=str(out_path),
            llm_usage=usage,
            errors=errors,
        )
