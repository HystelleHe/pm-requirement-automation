"""SkillSyncer 单测 —— 用临时目录 + mock NotionClient 验证 md 解析与 hash 缓存。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pm_workflow.agents.skill_sync import SkillSyncer, _extract_sections, _md_to_skill
from pm_workflow.config import Settings
from pm_workflow.notion import Skill, SkillStatus


# ---------- 工具：构造临时 settings 指向 tmp_path 下的目录 ----------


def _settings(tmp_path: Path) -> Settings:
    s = Settings(NOTION_API_KEY="t")
    # 把项目根目录的子目录指到 tmp_path
    # PROJECT_ROOT 是 frozen 计算的，最简单的办法是 monkey-patch 属性
    # 用 model_dump + 重新组装也行；这里直接动态覆盖更简单
    s.__class__.skill_library_dir = property(lambda self: tmp_path / "skill-library")  # type: ignore[assignment]
    s.__class__.outputs_dir = property(lambda self: tmp_path / "outputs")  # type: ignore[assignment]
    return s


# ---------- _extract_sections ----------


def test_extract_sections_with_titles():
    body = """前言

## System Prompt

你是一位 PM。

## User Prompt Template

需求：{{x}}
"""
    parts = _extract_sections(body)
    assert parts[""] == "前言"
    assert parts["System Prompt"].startswith("你是一位 PM")
    assert parts["User Prompt Template"].startswith("需求：")


def test_extract_sections_no_titles():
    parts = _extract_sections("纯正文，没标题")
    assert parts == {"": "纯正文，没标题"}


# ---------- _md_to_skill ----------


def test_md_to_skill_full(tmp_path: Path):
    f = tmp_path / "x.md"
    f.write_text(
        """---
name: 竞品发现
skill_key: competitor_discovery
status: Active
version: 0.2.0
description: 测试 skill
model_preference: moonshot
pipeline:
  - 竞品调研
input_variables:
  scenario: string
---

## System Prompt

prompt 正文

## User Prompt Template

模板 {{x}}
""",
        "utf-8",
    )
    skill = _md_to_skill(f)
    assert isinstance(skill, Skill)
    assert skill.name == "竞品发现"
    assert skill.skill_key == "competitor_discovery"
    assert skill.status == SkillStatus.ACTIVE
    assert skill.version == "0.2.0"
    assert skill.model_preference == "moonshot"
    assert skill.pipeline == ["竞品调研"]
    assert skill.system_prompt == "prompt 正文"
    assert "{{x}}" in skill.user_prompt_template
    # dict 类型的 input_variables 应被 json 序列化
    assert "scenario" in skill.input_variables


def test_md_to_skill_missing_key_raises(tmp_path: Path):
    f = tmp_path / "bad.md"
    f.write_text(
        """---
name: 缺 skill_key
---

body
""",
        "utf-8",
    )
    with pytest.raises(ValueError, match="skill_key"):
        _md_to_skill(f)


# ---------- SkillSyncer ----------


def _make_md(dir_: Path, key: str, version: str = "0.1.0") -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / f"{key}.md"
    p.write_text(
        f"""---
name: {key}
skill_key: {key}
status: Active
version: {version}
---

## System Prompt

sys

## User Prompt Template

usr
""",
        "utf-8",
    )
    return p


def test_sync_creates_then_skips_unchanged(tmp_path: Path):
    s = _settings(tmp_path)
    _make_md(s.skill_library_dir / "research", "skill_a")
    fake_notion = MagicMock()
    fake_notion.upsert_skill.return_value = "page-a"

    syncer = SkillSyncer(notion=fake_notion, settings=s)
    r1 = syncer.sync()
    assert r1 == {"skill_a": "created"}
    fake_notion.upsert_skill.assert_called_once()

    # 再跑一次，文件没变 → unchanged，不应再调 upsert
    fake_notion.upsert_skill.reset_mock()
    r2 = syncer.sync()
    assert r2 == {"skill_a": "unchanged"}
    fake_notion.upsert_skill.assert_not_called()


def test_sync_updates_when_content_changes(tmp_path: Path):
    s = _settings(tmp_path)
    p = _make_md(s.skill_library_dir / "prd", "skill_b", version="1.0.0")
    fake_notion = MagicMock()
    syncer = SkillSyncer(notion=fake_notion, settings=s)

    r1 = syncer.sync()
    assert r1 == {"skill_b": "created"}

    # 改文件内容
    p.write_text(p.read_text("utf-8").replace("1.0.0", "1.0.1"), "utf-8")

    fake_notion.upsert_skill.reset_mock()
    r2 = syncer.sync()
    assert r2 == {"skill_b": "updated"}
    fake_notion.upsert_skill.assert_called_once()


def test_sync_persists_cache(tmp_path: Path):
    s = _settings(tmp_path)
    _make_md(s.skill_library_dir / "research", "skill_c")
    syncer = SkillSyncer(notion=MagicMock(), settings=s)
    syncer.sync()
    cache_file = s.outputs_dir / ".skill_sync_cache.json"
    assert cache_file.exists()
    cache = json.loads(cache_file.read_text("utf-8"))
    assert "skill_c" in cache
    assert len(cache["skill_c"]) == 64  # sha256 hex
