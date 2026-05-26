"""从 LLM 文本响应中鲁棒提取 JSON。

为什么需要：reasoning 类模型返回的 content 偶尔会带 ```json 围栏 / 前置自由文本 /
甚至把 reasoning 内容混进 content。直接 json.loads 经常失败。
"""

from __future__ import annotations

import json
import re
from typing import Any


_FENCE_PATTERN = re.compile(r"```(?:json|JSON)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_from_text(text: str) -> Any:
    """三档兜底从 text 提取 JSON 对象：

    1. text 本身就是 JSON（最常见）
    2. ```json ... ``` 围栏
    3. 找第一个匹配的 {...} 或 [...]

    全部失败时抛 ValueError。
    """
    if not text:
        raise ValueError("text is empty")
    s = text.strip()

    # 1. 直接解析
    if s.startswith(("{", "[")):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass

    # 2. 围栏内
    m = _FENCE_PATTERN.search(s)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. 大括号匹配（取第一个能完整闭合的对象/数组）
    for opener, closer in (("{", "}"), ("[", "]")):
        i = s.find(opener)
        if i < 0:
            continue
        depth = 0
        in_string = False
        escape = False
        for j in range(i, len(s)):
            ch = s[j]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidate = s[i : j + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"No valid JSON found in text. Preview: {s[:200]!r}")
