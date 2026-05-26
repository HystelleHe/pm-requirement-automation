"""web scraper 模块的轻量测试 —— 不实际启 chromium（CI 慢且不稳）。

只验证模型结构和入口可调用；真实抓取的验证靠手工 smoke test。
"""

from pm_workflow.scrapers.web import PageContent


def test_pagecontent_defaults():
    p = PageContent(url="https://example.com")
    assert p.url == "https://example.com"
    assert p.status == 0
    assert p.title == ""
    assert p.text == ""
    assert p.error is None


def test_pagecontent_full():
    p = PageContent(
        url="https://example.com",
        final_url="https://example.com/index",
        status=200,
        title="Example",
        text="Hello world",
        html_size=12345,
    )
    assert p.status == 200
    assert p.title == "Example"
    assert p.html_size == 12345
