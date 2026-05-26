"""SkillLoader 单测 —— 验证模板渲染 + 缓存策略。"""

from unittest.mock import MagicMock

import pytest

from pm_workflow.config import Settings
from pm_workflow.llm import SkillLoader, render_template
from pm_workflow.notion import Skill, SkillStatus


def test_render_template_basic():
    out = render_template("Hello {{name}}, age {{age}}", {"name": "Wendy", "age": 30})
    assert out == "Hello Wendy, age 30"


def test_render_template_tolerates_spaces():
    out = render_template("Hi {{ name }}!", {"name": "X"})
    assert out == "Hi X!"


def test_render_template_keeps_missing_vars(caplog):
    """缺变量保留原样并 warn，不抛异常（便于调试）。"""
    out = render_template("Hi {{name}}, {{missing}}", {"name": "X"})
    assert "{{missing}}" in out
    assert "Hi X" in out


def test_render_template_none_becomes_empty():
    out = render_template("a={{x}}b", {"x": None})
    assert out == "a=b"


def test_loader_cache_hits_only_once():
    fake_notion = MagicMock()
    fake_notion.list_skills.return_value = [
        Skill(name="A", skill_key="a", status=SkillStatus.ACTIVE, system_prompt="sysA",
              user_prompt_template="A {{x}}"),
        Skill(name="B", skill_key="b", status=SkillStatus.DRAFT, system_prompt="sysB",
              user_prompt_template="B {{x}}"),
    ]
    settings = Settings(NOTION_API_KEY="t")
    loader = SkillLoader(notion=fake_notion, settings=settings)

    # 第 1 次 get：触发加载
    s = loader.get("a")
    assert s.skill_key == "a"
    # 第 2 次 get：缓存命中，不再调 SDK
    loader.get("a")
    fake_notion.list_skills.assert_called_once()


def test_loader_ignores_non_active():
    fake_notion = MagicMock()
    fake_notion.list_skills.return_value = [
        Skill(name="A", skill_key="a", status=SkillStatus.ACTIVE),
        Skill(name="B", skill_key="b", status=SkillStatus.DRAFT),
        Skill(name="C", skill_key="c", status=SkillStatus.DEPRECATED),
    ]
    loader = SkillLoader(notion=fake_notion, settings=Settings(NOTION_API_KEY="t"))
    assert loader.get("a").skill_key == "a"
    with pytest.raises(KeyError):
        loader.get("b")
    with pytest.raises(KeyError):
        loader.get("c")


def test_loader_render_returns_system_and_user():
    fake_notion = MagicMock()
    fake_notion.list_skills.return_value = [
        Skill(
            name="A",
            skill_key="a",
            status=SkillStatus.ACTIVE,
            system_prompt="你是 PM",
            user_prompt_template="场景：{{scenario}}",
        )
    ]
    loader = SkillLoader(notion=fake_notion, settings=Settings(NOTION_API_KEY="t"))
    sys_, usr = loader.render("a", scenario="自动化工具")
    assert sys_ == "你是 PM"
    assert usr == "场景：自动化工具"


def test_loader_reload_refreshes_cache():
    fake_notion = MagicMock()
    fake_notion.list_skills.side_effect = [
        [Skill(name="A", skill_key="a", status=SkillStatus.ACTIVE)],
        [
            Skill(name="A", skill_key="a", status=SkillStatus.ACTIVE),
            Skill(name="B", skill_key="b", status=SkillStatus.ACTIVE),
        ],
    ]
    loader = SkillLoader(notion=fake_notion, settings=Settings(NOTION_API_KEY="t"))
    loader.get("a")
    with pytest.raises(KeyError):
        loader.get("b")
    loader.reload()
    assert loader.get("b").skill_key == "b"
