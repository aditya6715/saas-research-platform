"""
tools/search_client.py
----------------------
Web search client wrapper (Tavily).
Returns normalized result dicts with url, title, snippet.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SearchResult:
    __slots__ = ("url", "title", "snippet", "score")

    def __init__(self, url: str, title: str, snippet: str, score: float = 0.5) -> None:
        self.url = url
        self.title = title
        self.snippet = snippet
        self.score = score

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "title": self.title, "snippet": self.snippet, "score": self.score}


class SearchClient:
    def __init__(self, api_key: str, max_results: int = 10) -> None:
        self.api_key = api_key
        self.max_results = max_results
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from tavily import TavilyClient
            self._client = TavilyClient(api_key=self.api_key)
        return self._client

    async def search(self, query: str, max_results: int | None = None) -> list[dict[str, Any]]:
        """
        Execute a Tavily web search and return normalized results.
        Runs the synchronous Tavily client in a thread pool.
        """
        n = max_results or self.max_results
        try:
            client = self._get_client()
            response = await asyncio.to_thread(
                client.search,
                query=query,
                max_results=n,
                include_answer=False,
                include_raw_content=False,
            )
            results = response.get("results", [])
            return [
                SearchResult(
                    url=r.get("url", ""),
                    title=r.get("title", ""),
                    snippet=r.get("content", "")[:400],
                    score=r.get("score", 0.5),
                ).to_dict()
                for r in results
                if r.get("url")
            ]
        except Exception as e:
            logger.warning("Search failed for query '%s': %s", query, e)
            return []
