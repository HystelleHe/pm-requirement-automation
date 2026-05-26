"""Skill Library 同步器 —— 本地 md 为 SoT，单向 push 到 Notion。

约定：
- `skill-library/**/*.md` 是 Prompt 的真源（Source of Truth）
- frontmatter 写元信息（name / skill_key / status / version / model_preference / pipeline / input_variables / output_schema / description）
- body 用 `## System Prompt` 和 `## User Prompt Template` 两个二级标题分隔 prompt 正文
- 启动时计算 (frontmatter + body) hash，仅 hash 变化的 skill 才 upsert，避免每次启动都打 Notion API
- hash 缓存写在 outputs/.skill_sync_cache.json（gitignored）

只读写 Skill Library 10 字段子集，其它 20+ 列保持原状。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import frontmatter

from pm_workflow.config import Settings, get_settings
from pm_workflow.notion import NotionClient, Skill, SkillStatus

logger = logging.getLogger(__name__)


CACHE_FILENAME = ".skill_sync_cache.json"

# md body 中分隔 prompt 章节的二级标题
_SECTION_PATTERN = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


# ===================================================================
# md 文件解析
# ===================================================================


def _extract_sections(body: str) -> dict[str, str]:
    """把 markdown body 按 `## 标题` 切成 {title: content} 字典。

    标题前的内容归到键 ""（empty）。
    """
    parts: dict[str, str] = {}
    matches = list(_SECTION_PATTERN.finditer(body))
    if not matches:
        return {"": body.strip()}
    # 标题前的内容
    if matches[0].start() > 0:
        parts[""] = body[: matches[0].start()].strip()
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        parts[title] = body[start:end].strip()
    return parts


def _md_to_skill(path: Path) -> Skill:
    """单个 md 文件 → Skill。"""
    post = frontmatter.load(path)
    meta: dict[str, Any] = post.metadata or {}
    if "skill_key" not in meta:
        raise ValueError(f"{path}: frontmatter 缺少 skill_key")
    if "name" not in meta:
        raise ValueError(f"{path}: frontmatter 缺少 name")

    sections = _extract_sections(post.content)
    system_prompt = sections.get("System Prompt", "")
    user_prompt_template = sections.get("User Prompt Template", "")

    # status 字段：支持 "Active" / "Draft" / "Deprecated"
    status_raw = str(meta.get("status", "Draft"))
    try:
        status = SkillStatus(status_raw)
    except ValueError:
        status = SkillStatus.DRAFT

    # input_variables / output_schema 在 frontmatter 里若是 dict/list，序列化为 JSON 字符串存
    def _maybe_json(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        return json.dumps(v, ensure_ascii=False)

    return Skill(
        name=str(meta["name"]),
        skill_key=str(meta["skill_key"]),
        status=status,
        version=str(meta.get("version", "0.1.0")),
        description=str(meta.get("description", "")),
        system_prompt=system_prompt,
        user_prompt_template=user_prompt_template,
        input_variables=_maybe_json(meta.get("input_variables")),
        output_schema=_maybe_json(meta.get("output_schema")),
        model_preference=str(meta.get("model_preference", "auto")),
        pipeline=list(meta.get("pipeline", []) or []),
    )


def _hash_file(path: Path) -> str:
    """对 md 文件原始字节算 sha256，作为内容指纹。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ===================================================================
# Sync 主流程
# ===================================================================


class SkillSyncer:
    def __init__(
        self,
        *,
        notion: NotionClient | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.notion = notion or NotionClient(settings=self.settings)
        self.cache_path = self.settings.outputs_dir / CACHE_FILENAME

    def _load_cache(self) -> dict[str, str]:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text("utf-8"))
        except json.JSONDecodeError:
            logger.warning("skill sync cache 损坏，重建：%s", self.cache_path)
            return {}

    def _save_cache(self, cache: dict[str, str]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), "utf-8")

    def discover_md_files(self) -> list[Path]:
        """扫描 skill-library/ 下所有 md 文件（递归）。"""
        root = self.settings.skill_library_dir
        if not root.exists():
            return []
        return sorted(root.rglob("*.md"))

    def sync(self) -> dict[str, str]:
        """执行一轮同步，返回 {skill_key: 'created'|'updated'|'unchanged'} 字典。"""
        cache = self._load_cache()
        results: dict[str, str] = {}
        new_cache: dict[str, str] = {}
        for md_path in self.discover_md_files():
            try:
                skill = _md_to_skill(md_path)
            except ValueError as e:
                logger.error("跳过 %s：%s", md_path, e)
                continue

            file_hash = _hash_file(md_path)
            cached_hash = cache.get(skill.skill_key)
            new_cache[skill.skill_key] = file_hash

            if cached_hash == file_hash:
                results[skill.skill_key] = "unchanged"
                logger.debug("Skill 未变化：%s", skill.skill_key)
                continue

            try:
                self.notion.upsert_skill(skill)
                results[skill.skill_key] = "updated" if cached_hash else "created"
            except Exception as e:
                logger.exception("upsert 失败：%s（%s）", skill.skill_key, e)
                # 失败时不更新 cache，下次启动还会重试
                new_cache.pop(skill.skill_key, None)
                results[skill.skill_key] = f"error: {e}"
                continue

        self._save_cache(new_cache)
        return results
