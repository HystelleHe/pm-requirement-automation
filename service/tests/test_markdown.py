"""markdown → notion blocks 转换测试。"""

from pm_workflow.notion.markdown import markdown_to_notion_blocks


def test_headings():
    md = "# 一级\n## 二级\n### 三级"
    blocks = markdown_to_notion_blocks(md)
    assert [b["type"] for b in blocks] == ["heading_1", "heading_2", "heading_3"]
    assert blocks[1]["heading_2"]["rich_text"][0]["text"]["content"] == "二级"


def test_paragraph_and_bullet_and_quote():
    md = """前言段落。

- 列表项一
- 列表项二

> 引用句子
"""
    blocks = markdown_to_notion_blocks(md)
    types = [b["type"] for b in blocks]
    assert types == [
        "paragraph",
        "bulleted_list_item",
        "bulleted_list_item",
        "quote",
    ]


def test_truncates_long_text():
    long_line = "x" * 3000
    blocks = markdown_to_notion_blocks(long_line)
    content = blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]
    assert len(content) <= 2000
    assert content.endswith("...")


def test_code_fence_falls_back_to_paragraph():
    md = "```python\nprint('hi')\nx = 1\n```\n后面"
    blocks = markdown_to_notion_blocks(md)
    types = [b["type"] for b in blocks]
    # ``` 行被吃掉，内部行变成 paragraph
    assert types == ["paragraph", "paragraph", "paragraph"]
    assert "print" in blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]


def test_empty_lines_skipped():
    md = "a\n\n\nb"
    blocks = markdown_to_notion_blocks(md)
    assert len(blocks) == 2
