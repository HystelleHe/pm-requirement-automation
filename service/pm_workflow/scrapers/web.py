"""公开网页抓取 —— Playwright headless chromium + trafilatura 正文提取。

为什么不只用 httpx：
- 越来越多产品页是 JS 渲染（SPA），直接 GET 拿到的是空骨架
- chromium 跑 JS 才能拿到真实 DOM 内容

为什么用 trafilatura 而不是直接 inner_text：
- inner_text("body") 会把导航/页脚/cookie 提示等噪音也拿进来
- trafilatura 专门做正文检测，给 LLM 看的 token 量能减少 10×

设计：每次 fetch 都开/关一次 browser context，不维护长连接 —— 简单稳定，
单次需求平均也就抓 5-10 个页面，开销可以接受。
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import trafilatura
from playwright.sync_api import Browser, sync_playwright
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Playwright 默认 UA 会被一些站点识别屏蔽，伪装成主流桌面 chrome
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class PageContent(BaseModel):
    """单页抓取结果。"""

    url: str
    final_url: str = ""  # 经过重定向后的最终 URL
    status: int = 0  # HTTP 状态码
    title: str = ""
    text: str = ""  # trafilatura 提取的正文
    html_size: int = 0  # 原 HTML 字节数
    error: str | None = None
    extras: dict = Field(default_factory=dict)


@contextmanager
def _browser_context() -> Iterator[Browser]:
    """开/关 chromium 的统一入口；用 context manager 保证 cleanup。"""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",  # 隐藏 webdriver 标识
                "--disable-dev-shm-usage",  # 容器内 /dev/shm 通常太小
                "--no-sandbox",  # 容器内必需
            ],
        )
        try:
            yield browser
        finally:
            browser.close()


def fetch_page(
    url: str,
    *,
    timeout_ms: int = 15000,
    wait_after_load_ms: int = 1500,
    extract_text: bool = True,
) -> PageContent:
    """抓单个 URL 并返回正文。

    参数：
      timeout_ms: 整个 navigation 的超时
      wait_after_load_ms: domcontentloaded 后再 sleep 一会儿等 JS 异步内容（SPA 常用）
      extract_text: False 则只返回 title/status，不跑 trafilatura（省时间）
    """
    try:
        with _browser_context() as browser:
            return _fetch_with(browser, url, timeout_ms, wait_after_load_ms, extract_text)
    except Exception as e:
        logger.exception("fetch_page 失败：%s", url)
        return PageContent(url=url, error=f"{type(e).__name__}: {e}")


def fetch_pages(
    urls: list[str],
    *,
    timeout_ms: int = 15000,
    wait_after_load_ms: int = 1500,
    extract_text: bool = True,
) -> list[PageContent]:
    """批量抓取 —— 共用一个 browser 实例节省启动开销（一次需求抓 5+ URL 时）。"""
    results: list[PageContent] = []
    try:
        with _browser_context() as browser:
            for u in urls:
                try:
                    results.append(
                        _fetch_with(browser, u, timeout_ms, wait_after_load_ms, extract_text)
                    )
                except Exception as e:
                    logger.exception("fetch_pages 子项失败：%s", u)
                    results.append(PageContent(url=u, error=f"{type(e).__name__}: {e}"))
    except Exception as e:
        logger.exception("fetch_pages 整体失败")
        # 整体失败：把剩余 URL 全部标记
        for u in urls[len(results):]:
            results.append(PageContent(url=u, error=f"{type(e).__name__}: {e}"))
    return results


def _fetch_with(
    browser: Browser,
    url: str,
    timeout_ms: int,
    wait_after_load_ms: int,
    extract_text: bool,
) -> PageContent:
    """实际抓取逻辑；调用方负责 browser 生命周期。"""
    context = browser.new_context(user_agent=_UA, viewport={"width": 1280, "height": 800})
    page = context.new_page()
    try:
        resp = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        if wait_after_load_ms > 0:
            page.wait_for_timeout(wait_after_load_ms)
        title = page.title() or ""
        html = page.content()
        final_url = page.url
        status = resp.status if resp else 0

        text = ""
        if extract_text and html:
            try:
                text = trafilatura.extract(
                    html,
                    include_comments=False,
                    include_tables=True,
                    include_links=False,
                    favor_recall=True,  # 倾向召回多一点正文，缺失关键内容比噪音更难补救
                ) or ""
            except Exception as e:
                logger.warning("trafilatura 提取失败 %s：%s", url, e)

        return PageContent(
            url=url,
            final_url=final_url,
            status=status,
            title=title,
            text=text,
            html_size=len(html),
        )
    finally:
        context.close()
