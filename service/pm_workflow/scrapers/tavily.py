"""Tavily 搜索客户端封装。

为什么不直接用 tavily-python：
- SDK 返回原始 dict，结构有 schema 变动风险
- 我们把响应包成 Pydantic 模型，方便上层 type-safe 处理
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field
from tavily import TavilyClient  # type: ignore[import-untyped]

from pm_workflow.config import Settings, get_settings

logger = logging.getLogger(__name__)


class TavilyResult(BaseModel):
    """单条搜索结果。"""

    title: str
    url: str
    content: str = ""  # snippet
    score: float = 0.0
    raw_content: str | None = None  # include_raw_content=True 时填充


class TavilyResponse(BaseModel):
    """一次 Tavily 搜索的完整响应。"""

    query: str
    answer: str | None = None
    results: list[TavilyResult] = Field(default_factory=list)
    response_time: float = 0.0


class TavilySearcher:
    """同步客户端。Tavily 官方限速宽松，单进程不用做额外的并发限制。"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        if not self.settings.tavily_api_key:
            raise RuntimeError("TAVILY_API_KEY 未配置，无法初始化 TavilySearcher")
        self._client = TavilyClient(api_key=self.settings.tavily_api_key)

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        search_depth: Literal["basic", "advanced"] = "basic",
        include_answer: bool = True,
        include_raw_content: bool = False,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> TavilyResponse:
        """执行一次搜索。

        参数:
          max_results: 1-20
          search_depth: basic 1 credit；advanced 2 credits 但质量更高
          include_answer: True 让 Tavily 返回基于结果的 1-2 句话总结（很有用）
          include_raw_content: 抓页面正文（增加 1 credit/结果，且变慢）
        """
        kwargs = {
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
        }
        if include_domains:
            kwargs["include_domains"] = include_domains
        if exclude_domains:
            kwargs["exclude_domains"] = exclude_domains

        raw = self._client.search(**kwargs)
        logger.debug("Tavily query=%r results=%d", query, len(raw.get("results", [])))

        return TavilyResponse(
            query=raw.get("query", query),
            answer=raw.get("answer"),
            results=[
                TavilyResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    content=r.get("content", ""),
                    score=r.get("score", 0.0),
                    raw_content=r.get("raw_content"),
                )
                for r in raw.get("results", [])
            ],
            response_time=raw.get("response_time", 0.0),
        )
