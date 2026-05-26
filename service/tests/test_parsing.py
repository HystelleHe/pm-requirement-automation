"""LLM JSON 鲁棒解析测试。"""

import pytest

from pm_workflow.llm.parsing import parse_json_from_text


def test_plain_json_object():
    assert parse_json_from_text('{"a": 1, "b": [2, 3]}') == {"a": 1, "b": [2, 3]}


def test_plain_json_array():
    assert parse_json_from_text("[1, 2, 3]") == [1, 2, 3]


def test_json_in_fence():
    text = """好的，以下是结果：
```json
{"name": "Notion", "url": "https://notion.com"}
```
请审阅。"""
    assert parse_json_from_text(text) == {"name": "Notion", "url": "https://notion.com"}


def test_json_in_fence_without_lang():
    text = "```\n[1, 2]\n```"
    assert parse_json_from_text(text) == [1, 2]


def test_json_embedded_in_text():
    text = '前面有一些自由文本... 这里是结果 {"x": "y"} 后面也有 garbage'
    assert parse_json_from_text(text) == {"x": "y"}


def test_json_with_nested_braces():
    text = '前置文本 {"a": {"b": {"c": 1}}} 后置'
    assert parse_json_from_text(text) == {"a": {"b": {"c": 1}}}


def test_json_string_containing_braces():
    """字符串里的 } 不应误判为闭合。"""
    text = '{"msg": "hello {world}"}'
    assert parse_json_from_text(text) == {"msg": "hello {world}"}


def test_invalid_raises():
    with pytest.raises(ValueError):
        parse_json_from_text("纯文本完全没有 JSON")


def test_empty_raises():
    with pytest.raises(ValueError):
        parse_json_from_text("")
