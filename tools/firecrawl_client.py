"""
tools/firecrawl_client.py
-------------------------
Cache-aware Firecrawl SDK wrapper.
Returns clean markdown from documentation pages.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.cache import DiskCache

logger = logging.getLogger(__name__)


class FirecrawlClient:
    def __init__(self, api_key: str, cache: DiskCache) -> None:
        self.api_key = api_key
        self.cache = cache
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from firecrawl import FirecrawlApp

            self._client = FirecrawlApp(api_key=self.api_key)
        return self._client

    async def scrape(self, url: str) -> str | None:
        """
        Scrape a URL and return clean markdown content.
        Uses disk cache — returns cached content if within TTL.
        """
        # Check cache first
        cached = self.cache.get(url)
        if cached:
            logger.debug("Cache HIT: %s", url)
            return cached.content

        logger.debug("Cache MISS — fetching: %s", url)

        try:
            client = self._get_client()
            response = await asyncio.to_thread(
                client.scrape_url,
                url,
                params={"formats": ["markdown"], "onlyMainContent": True},
            )

            markdown = None
            if isinstance(response, dict):
                markdown = response.get("markdown") or response.get("content")
            elif hasattr(response, "markdown"):
                markdown = response.markdown
            elif hasattr(response, "content"):
                markdown = response.content

            if markdown and len(markdown.strip()) > 100:
                self.cache.set(url, markdown, content_type="text/markdown")
                return markdown

            logger.warning("Firecrawl returned empty content for %s", url)
            return None

        except Exception as e:
            logger.warning("Firecrawl error for %s: %s", url, e)
            return None

    async def crawl(self, url: str, max_pages: int = 10) -> list[dict[str, Any]]:
        """
        Crawl a site and return list of {url, markdown} dicts.
        """
        try:
            client = self._get_client()
            response = await asyncio.to_thread(
                client.crawl_url,
                url,
                params={
                    "limit": max_pages,
                    "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True},
                },
            )
            pages = []
            data = response if isinstance(response, list) else response.get("data", [])
            for page in data:
                page_url = page.get("metadata", {}).get("sourceURL") or page.get("url", "")
                markdown = page.get("markdown") or page.get("content", "")
                if page_url and markdown:
                    self.cache.set(page_url, markdown, content_type="text/markdown")
                    pages.append({"url": page_url, "markdown": markdown})
            return pages
        except Exception as e:
            logger.warning("Firecrawl crawl error for %s: %s", url, e)
            return []
