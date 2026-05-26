"""轻量 Markdown → Notion blocks 转换。

支持的 markdown 元素（足够 PRD / 调研报告这类长文用）：
- `# / ## / ###` 三级标题 → heading_1/2/3
- `- / *` 无序列表 → bulleted_list_item
- `> ` 引用 → quote
- 其他 → paragraph

不支持的（暂时）：
- inline 加粗/斜体/链接（保留原文，不渲染样式）
- 表格（Notion table 结构复杂，单独后续支持）
- 代码块 ``` ... ``` （目前按 paragraph 处理）

Notion API 限制：
- rich_text 单段 content 上限 2000 字符 —— 我们 truncate 到 1990 + "..."
- pages.create children 上限 100 块 —— 调用方负责分批
"""

from __future__ import annotations

import re

_MAX_TEXT_LEN = 1990
_TRUNC_SUFFIX = "..."


def _truncate(text: str) -> str:
    if len(text) <= _MAX_TEXT_LEN:
        return text
    return text[: _MAX_TEXT_LEN - len(_TRUNC_SUFFIX)] + _TRUNC_SUFFIX


def _rich_text_block(text: str) -> list[dict]:
    """构造单段 rich_text 数组，自动 truncate。"""
    if not text:
        return []
    return [{"type": "text", "text": {"content": _truncate(text)}}]


def _heading_block(text: str, level: int) -> dict:
    key = f"heading_{level}"
    return {
        "object": "block",
        "type": key,
        key: {"rich_text": _rich_text_block(text)},
    }


def _paragraph_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text_block(text)},
    }


def _bullet_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text_block(text)},
    }


def _quote_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "quote",
        "quote": {"rich_text": _rich_text_block(text)},
    }


_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
_BULLET_RE = re.compile(r"^[\-\*]\s+(.+)$")
_QUOTE_RE = re.compile(r"^>\s*(.*)$")


def markdown_to_notion_blocks(md: str) -> list[dict]:
    """把 markdown 文本转换为 Notion block 列表（JSON 兼容 children）。"""
    blocks: list[dict] = []
    in_code = False  # 简单处理：fenced code 内容降级为 paragraph
    for raw in md.split("\n"):
        line = raw.rstrip()

        # 代码块开关
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            if line:
                blocks.append(_paragraph_block(line))
            continue

        if not line.strip():
            continue

        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            blocks.append(_heading_block(m.group(2).strip(), level))
            continue

        m = _BULLET_RE.match(line)
        if m:
            blocks.append(_bullet_block(m.group(1).strip()))
            continue

        m = _QUOTE_RE.match(line)
        if m:
            blocks.append(_quote_block(m.group(1).strip()))
            continue

        blocks.append(_paragraph_block(line))
    return blocks
