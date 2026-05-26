"""PRD 撰写 Agent —— Kimi 生成 → GLM 跨家 Critic → Kimi 修订循环（最多 N 轮）。

数据流：
- 输入：Requirement（含 req_id）+ research.md（默认从 outputs/ 读）+ breakdown.md（同）
- 第 1 轮：Kimi 按 prd_writer skill 出初版 prd_markdown
- 第 k 轮 critic：GLM 按 prd_critic skill 评分 + 列 issues（含 severity）
- 若 needs_revision 且 round < CRITIC_MAX_ROUNDS：Kimi 按 issues 修订（沿用 prd_writer system，
  user 拼上一版 PRD + critic 反馈）→ 再 critic → 直到不需要修订或达上限
- 输出：最终版落 outputs/{req_id}/prd.md；prd_raw.json 含全部修订历史
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pm_workflow.agents.models import (
    CriticIssue,
    CriticReview,
    PRDResult,
    Severity,
)
from pm_workflow.config import Settings, get_settings
from pm_workflow.llm import LLMRouter, LLMTask, SkillLoader
from pm_workflow.llm.parsing import parse_json_from_text
from pm_workflow.notion.models import Requirement

logger = logging.getLogger(__name__)


# ===================================================================
# 工具
# ===================================================================


def _accumulate_usage(acc: dict[str, int], delta: dict[str, Any]) -> None:
    """把单次 chat 的 usage（OpenAI 风格 dict）累加进 acc。

    OpenAI usage 字段：prompt_tokens / completion_tokens / total_tokens
    reasoning 模型额外有 completion_tokens_details.reasoning_tokens（嵌套），暂不展开。
    """
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        v = delta.get(k)
        if isinstance(v, int):
            acc[k] = acc.get(k, 0) + v


# ===================================================================
# Critic 返回 JSON → CriticReview
# ===================================================================


def _parse_review(raw: dict[str, Any], round_no: int, errors: list[str]) -> CriticReview:
    """容错地把 LLM 返回的 critic JSON 转 CriticReview。"""
    review = CriticReview(round=round_no)
    if not isinstance(raw, dict):
        errors.append(f"critic 返回不是 dict：{type(raw).__name__}")
        return review

    try:
        review.overall_score = int(raw.get("overall_score") or 0)
    except (TypeError, ValueError):
        review.overall_score = 0

    review.needs_revision = bool(raw.get("needs_revision"))
    review.summary = str(raw.get("summary") or "").strip()

    for i, item in enumerate(raw.get("issues") or []):
        if not isinstance(item, dict):
            errors.append(f"issues[{i}] 不是 dict，跳过")
            continue
        sev = str(item.get("severity") or "P1").upper()
        if sev not in ("P0", "P1", "P2"):
            errors.append(f"issues[{i}].severity={sev!r} 非法，落到 P1")
            sev = "P1"
        review.issues.append(
            CriticIssue(
                severity=sev,  # type: ignore[arg-type]
                section=str(item.get("section") or "").strip(),
                problem=str(item.get("problem") or "").strip(),
                suggestion=str(item.get("suggestion") or "").strip(),
            )
        )

    # 兜底：模型如果忘了置 needs_revision，按 severity 推断（任一 P0 或 ≥2 个 P1）
    if not review.needs_revision:
        p0 = sum(1 for x in review.issues if x.severity == "P0")
        p1 = sum(1 for x in review.issues if x.severity == "P1")
        if p0 >= 1 or p1 >= 2:
            review.needs_revision = True

    review.errors = errors[:]  # snapshot
    return review


def _format_issues_for_revision(issues: list[CriticIssue]) -> str:
    """把 critic 问题清单格式化为修订 prompt 用的 markdown 块。"""
    if not issues:
        return "（无具体问题，按整体可读性优化即可）"
    lines: list[str] = []
    for i, x in enumerate(issues, 1):
        head = f"{i}. **[{x.severity}] {x.section}** —— {x.problem}"
        lines.append(head)
        if x.suggestion:
            lines.append(f"   修订建议：{x.suggestion}")
    return "\n".join(lines)


# ===================================================================
# PRDAgent
# ===================================================================


class PRDAgent:
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

    # ---------- 文件读取 ----------

    def _load_md(self, req_id: str, name: str) -> str:
        p: Path = self.settings.outputs_dir / req_id / name
        if not p.exists():
            raise FileNotFoundError(
                f"找不到上游产出：{p}。请先跑对应阶段产出 {name}"
            )
        return p.read_text("utf-8")

    # ---------- 生成 ----------

    def _generate_initial(
        self,
        req: Requirement,
        breakdown_md: str,
        research_md: str,
        acc_usage: dict[str, int],
    ) -> str:
        """初版 PRD：直接走 prd_writer skill。"""
        system, user = self.skills.render(
            "prd_writer",
            requirement_name=req.name,
            scenario=req.scenario,
            breakdown=breakdown_md,
            research_summary=research_md,
        )
        resp = self.llm.chat(
            LLMTask.PRD_WRITER,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        _accumulate_usage(acc_usage, resp.usage)
        return resp.content.strip()

    def _revise(
        self,
        req: Requirement,
        breakdown_md: str,
        research_md: str,
        prev_prd: str,
        review: CriticReview,
        acc_usage: dict[str, int],
    ) -> str:
        """按 critic 反馈修订上一版 PRD。沿用 prd_writer 的 system prompt。"""
        skill = self.skills.get("prd_writer")
        system = skill.system_prompt
        # 拿原 user 模板渲染一下（保留原始上下文），再追加修订指令
        from pm_workflow.llm.skill_loader import render_template

        base_user = render_template(
            skill.user_prompt_template,
            {
                "requirement_name": req.name,
                "scenario": req.scenario,
                "breakdown": breakdown_md,
                "research_summary": research_md,
            },
        )

        issues_text = _format_issues_for_revision(review.issues)
        user = (
            f"{base_user}\n\n"
            f"---\n\n"
            f"## 上一版 PRD\n\n"
            f"{prev_prd}\n\n"
            f"---\n\n"
            f"## 审校反馈（第 {review.round} 轮 critic，总分 {review.overall_score}）\n\n"
            f"{review.summary}\n\n"
            f"**需修复的问题**：\n{issues_text}\n\n"
            f"---\n\n"
            f"请基于上一版 PRD 与审校反馈，**输出完整修订后的 PRD（markdown）**。"
            f"保留好的部分，针对 P0/P1 问题逐条修订，不要只列 diff。"
        )
        resp = self.llm.chat(
            LLMTask.PRD_WRITER,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        _accumulate_usage(acc_usage, resp.usage)
        return resp.content.strip()

    # ---------- Critic ----------

    def _critique(
        self,
        req: Requirement,
        breakdown_md: str,
        research_md: str,
        prd_md: str,
        round_no: int,
        acc_usage: dict[str, int],
    ) -> CriticReview:
        system, user = self.skills.render(
            "prd_critic",
            requirement_name=req.name,
            scenario=req.scenario,
            breakdown=breakdown_md,
            research_summary=research_md,
            prd_markdown=prd_md,
        )
        resp = self.llm.chat(
            LLMTask.PRD_CRITIC,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        _accumulate_usage(acc_usage, resp.usage)

        errors: list[str] = []
        try:
            raw = parse_json_from_text(resp.content)
        except ValueError as e:
            errors.append(f"critic 返回无法解析为 JSON：{e}（preview: {resp.content[:200]!r}）")
            raw = {}

        review = _parse_review(raw if isinstance(raw, dict) else {}, round_no, errors)
        review.llm_usage = resp.usage
        return review

    # ---------- 主入口 ----------

    def generate(
        self,
        req: Requirement,
        *,
        research_markdown: str | None = None,
        breakdown_markdown: str | None = None,
        req_id: str | None = None,
    ) -> PRDResult:
        """对单个需求跑 PRD 生成 + Critic 修订循环。

        参数:
          research_markdown / breakdown_markdown: 上游产出；不传则按 req_id 从 outputs/ 读
          req_id: outputs/{req_id}/ 目录名；不传用 req.req_id；都没有时用 page_id 截断
        """
        errors: list[str] = []
        rid = req_id or req.req_id or f"req-{req.page_id[:8]}"

        if research_markdown is None:
            research_markdown = self._load_md(rid, "research.md")
        if breakdown_markdown is None:
            breakdown_markdown = self._load_md(rid, "breakdown.md")

        acc_usage: dict[str, int] = {}
        reviews: list[CriticReview] = []

        # ===== 初版 =====
        try:
            prd_md = self._generate_initial(req, breakdown_markdown, research_markdown, acc_usage)
        except Exception as e:
            logger.exception("PRD 初版生成崩溃")
            raise

        if not prd_md.strip():
            errors.append("PRD 初版为空（LLM 返回空 content）")

        # ===== Critic 修订循环 =====
        max_rounds = max(0, int(self.settings.critic_max_rounds))
        revisions = 0
        out_dir = self.settings.outputs_dir / rid
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "prd_v0.md").write_text(prd_md, "utf-8")  # 初版备份

        for round_no in range(1, max_rounds + 1):
            try:
                review = self._critique(
                    req,
                    breakdown_markdown,
                    research_markdown,
                    prd_md,
                    round_no,
                    acc_usage,
                )
            except Exception as e:
                logger.exception("Critic 第 %d 轮失败，跳出循环：%s", round_no, e)
                errors.append(f"critic round {round_no} 异常：{type(e).__name__}: {e}")
                break

            reviews.append(review)
            logger.info(
                "Critic 第 %d 轮：score=%d needs_revision=%s issues=%d",
                round_no,
                review.overall_score,
                review.needs_revision,
                len(review.issues),
            )

            if not review.needs_revision:
                break

            # 还需要修订 —— 但若已到最后一轮，不再生成（修订完了也没机会再 critic）
            if round_no >= max_rounds:
                logger.info("Critic 仍要求修订但已达上限 %d 轮，沿用当前版", max_rounds)
                break

            try:
                prd_md = self._revise(
                    req,
                    breakdown_markdown,
                    research_markdown,
                    prd_md,
                    review,
                    acc_usage,
                )
                revisions += 1
                (out_dir / f"prd_v{revisions}.md").write_text(prd_md, "utf-8")
            except Exception as e:
                logger.exception("修订第 %d 轮失败，沿用上一版：%s", round_no, e)
                errors.append(f"revise round {round_no} 异常：{type(e).__name__}: {e}")
                break

        # ===== 落盘 =====
        out_path = out_dir / "prd.md"
        out_path.write_text(prd_md, "utf-8")

        raw_path = out_dir / "prd_raw.json"
        raw_path.write_text(
            json.dumps(
                {
                    "requirement": req.model_dump(mode="json"),
                    "revisions": revisions,
                    "reviews": [r.model_dump(mode="json") for r in reviews],
                    "llm_usage": acc_usage,
                    "errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            "utf-8",
        )

        return PRDResult(
            req_id=rid,
            req_page_id=req.page_id,
            requirement_name=req.name,
            prd_markdown=prd_md,
            revisions=revisions,
            reviews=reviews,
            output_path=str(out_path),
            llm_usage=acc_usage,
            errors=errors,
        )
