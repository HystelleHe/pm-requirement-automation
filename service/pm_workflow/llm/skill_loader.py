"""Skill 加载器 —— 从 Notion 拉 active skill 缓存 + 渲染 prompt 模板。

agent 实现的统一入口：
    loader = SkillLoader()
    system, user = loader.render("competitor_discovery", scenario="...", specified_competitors="...")
    resp = router.chat(LLMTask.KEYWORD_DISCOVERY, [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])
"""

from __future__ import annotations

import logging
import re

from pm_workflow.config import Settings, get_settings
from pm_workflow.notion import NotionClient, Skill, SkillStatus

logger = logging.getLogger(__name__)

# 双花括号占位符；支持下划线/字母数字变量名
_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render_template(template: str, variables: dict[str, object]) -> str:
    """把 {{var}} 替换为 variables[var] 的字符串形式；缺失的变量保留原样。

    用正则替换而不是 str.replace，理由：
    - 容忍 `{{ name }}` 这种带空格的写法
    - 缺失变量不报错，便于调试看出谁没传
    """

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in variables:
            logger.warning("模板变量缺失：%s", key)
            return m.group(0)
        val = variables[key]
        if val is None:
            return ""
        return str(val)

    return _VAR_PATTERN.sub(_sub, template)


class SkillLoader:
    """进程内 skill 缓存；启动后第一次 get() 时全量加载。"""

    def __init__(
        self,
        *,
        notion: NotionClient | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self._notion = notion
        self._cache: dict[str, Skill] = {}
        self._loaded = False

    @property
    def notion(self) -> NotionClient:
        # 延迟实例化，方便测试时 inject mock
        if self._notion is None:
            self._notion = NotionClient(settings=self.settings)
        return self._notion

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        skills = self.notion.list_skills()
        self._cache = {s.skill_key: s for s in skills if s.status == SkillStatus.ACTIVE}
        self._loaded = True
        logger.info("Skill 缓存加载完成：%d 个 active skill", len(self._cache))

    def get(self, skill_key: str) -> Skill:
        """按 skill_key 取，找不到抛 KeyError。"""
        self._ensure_loaded()
        if skill_key not in self._cache:
            raise KeyError(f"Skill not found: {skill_key}（已加载 keys: {list(self._cache)}）")
        return self._cache[skill_key]

    def render(self, skill_key: str, **variables: object) -> tuple[str, str]:
        """返回 (system_prompt, rendered_user_prompt)。"""
        skill = self.get(skill_key)
        return skill.system_prompt, render_template(skill.user_prompt_template, variables)

    def reload(self) -> None:
        """强制重新从 Notion 加载（运行时 prompt 有改动后调）。"""
        self._loaded = False
        self._cache.clear()
