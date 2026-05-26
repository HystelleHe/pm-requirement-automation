"""BreakdownAgent 单测 —— mock LLM 验证 JSON 解析 + markdown 渲染。"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pm_workflow.agents.breakdown import BreakdownAgent, render_breakdown_markdown
from pm_workflow.agents.models import UserStory
from pm_workflow.config import Settings
from pm_workflow.llm import LLMRouter, SkillLoader
from pm_workflow.llm.router import ChatResponse, LLMTask
from pm_workflow.notion.models import Requirement


def _settings(tmp_path: Path) -> Settings:
    s = Settings(NOTION_API_KEY="t", LLM_GATEWAY_TOKEN="t")
    s.__class__.skill_library_dir = property(lambda self: tmp_path / "skill-library")  # type: ignore[assignment]
    s.__class__.outputs_dir = property(lambda self: tmp_path / "outputs")  # type: ignore[assignment]
    return s


def test_render_groups_by_priority():
    stories = [
        UserStory(story="作为 A 我希望 X 以便 Y", priority="P1"),
        UserStory(story="作为 B 我希望 Z 以便 W", priority="P0"),
        UserStory(story="作为 C 我希望 M 以便 N", priority="P0"),
    ]
    md = render_breakdown_markdown("测试需求", stories, [], [])
    # P0 应排在 P1 前面
    p0_pos = md.index("### P0")
    p1_pos = md.index("### P1")
    assert p0_pos < p1_pos
    # P0 组有 2 条
    assert "### P0（2 条）" in md
    assert "### P1（1 条）" in md


def test_render_includes_oos_and_open_questions():
    md = render_breakdown_markdown(
        "X", [], out_of_scope=["不做账号体系"], open_questions=["权限模型谁来定？"]
    )
    assert "Out of Scope" in md
    assert "不做账号体系" in md
    assert "开放问题" in md
    assert "权限模型谁来定？" in md


def test_parse_stories_tolerates_bad_priority(tmp_path: Path):
    """非法 priority 应降级为 P1 + 记入 errors，而不是 raise。"""
    agent = BreakdownAgent(
        llm=MagicMock(spec=LLMRouter),
        skills=MagicMock(spec=SkillLoader),
        settings=_settings(tmp_path),
    )
    errors: list[str] = []
    stories, oos, oq = agent._parse_stories(
        {
            "user_stories": [
                {"story": "OK", "priority": "P9", "acceptance_criteria": ["a"]},
                {"story": "x"},  # 缺 priority，默认 P1
                "not a dict",  # 非法元素，应跳过
            ],
            "out_of_scope": ["不做X"],
            "open_questions": ["问题1"],
        },
        errors,
    )
    assert len(stories) == 2
    assert stories[0].priority == "P1"  # P9 落到 P1
    assert stories[1].priority == "P1"
    assert oos == ["不做X"]
    assert oq == ["问题1"]
    # errors 应记录了非法的 priority 和非 dict 元素
    assert any("P9" in e or "非法" in e for e in errors)


def test_breakdown_reads_research_md(tmp_path: Path):
    s = _settings(tmp_path)
    # 准备上游 research.md
    out = s.outputs_dir / "req-x" / "research.md"
    out.parent.mkdir(parents=True)
    out.write_text("# 调研结果\n竞品 A 的功能...", "utf-8")

    fake_llm = MagicMock(spec=LLMRouter)
    fake_llm.chat.return_value = ChatResponse(
        task=LLMTask.BREAKDOWN,
        model="moonshotai/Kimi-K2-Thinking",
        content='{"user_stories":[{"story":"作为 PM 我希望自动调研以便省时","priority":"P0","acceptance_criteria":["输入场景能生成 5 个竞品"]}],"out_of_scope":["不做销售"],"open_questions":["谁审报告？"]}',
        usage={"total_tokens": 100},
    )
    fake_skills = MagicMock(spec=SkillLoader)
    fake_skills.render.return_value = ("sys", "user prompt with research...")

    agent = BreakdownAgent(llm=fake_llm, skills=fake_skills, settings=s)
    req = Requirement(page_id="page-x", name="测试需求", scenario="测试场景")
    result = agent.breakdown(req, req_id="req-x")

    assert len(result.user_stories) == 1
    assert result.user_stories[0].priority == "P0"
    assert result.out_of_scope == ["不做销售"]
    assert (s.outputs_dir / "req-x" / "breakdown.md").exists()
    assert (s.outputs_dir / "req-x" / "breakdown_raw.json").exists()
    # 验证 LLM 收到了 research.md 内容
    sys_prompt, user_prompt = fake_skills.render.call_args.args[0], None
    skill_call_kwargs = fake_skills.render.call_args.kwargs
    assert "research_markdown" in skill_call_kwargs
    assert "竞品 A" in skill_call_kwargs["research_markdown"]


def test_breakdown_missing_research_raises(tmp_path: Path):
    s = _settings(tmp_path)
    agent = BreakdownAgent(
        llm=MagicMock(spec=LLMRouter),
        skills=MagicMock(spec=SkillLoader),
        settings=s,
    )
    req = Requirement(page_id="p", name="x", scenario="y")
    with pytest.raises(FileNotFoundError, match="research.md"):
        agent.breakdown(req, req_id="not-exist")
