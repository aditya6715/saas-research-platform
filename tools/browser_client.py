"""
tools/browser_client.py
-----------------------
Browser Use + Playwright wrapper for interactive page extraction.
Used when Firecrawl fails (bot detection, JS-heavy pages)
and for developer portal verification.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from core.cache import DiskCache

logger = logging.getLogger(__name__)


class BrowserClient:
    """
    Wraps Browser Use for LLM-guided extraction and raw Playwright for screenshots.
    Falls back gracefully when browser automation is unavailable.
    """

    def __init__(self, cache: DiskCache, openai_api_key: str) -> None:
        self.cache = cache
        self.openai_api_key = openai_api_key
        self._playwright: Any = None

    async def extract_markdown(self, url: str, instruction: str | None = None) -> str | None:
        """
        Extract markdown content from a URL using Browser Use.
        Falls back to raw Playwright + html2text if Browser Use fails.
        """
        cache_key = f"browser:{url}"
        cached = self.cache.get(cache_key)
        if cached:
            logger.debug("Browser cache HIT: %s", url)
            return cached.content

        instruction = (
            instruction
            or "Extract the main content of this page as clean markdown text. Include any authentication, API, and pricing information."
        )

        # Try Browser Use first
        content = await self._try_browser_use(url, instruction)

        # Fallback: raw Playwright
        if not content:
            content = await self._try_playwright_extract(url)

        if content:
            self.cache.set(cache_key, content, content_type="text/markdown", ttl_seconds=86400)

        return content

    async def screenshot(self, url: str, output_path: str) -> bool:
        """Capture a full-page screenshot using Playwright."""
        try:
            from playwright.async_api import async_playwright

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                ctx = await browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                )
                page = await ctx.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    await page.wait_for_timeout(2000)
                    await page.screenshot(path=output_path, full_page=True)
                    return True
                except Exception as e:
                    logger.warning("Screenshot failed for %s: %s", url, e)
                    return False
                finally:
                    await browser.close()
        except ImportError:
            logger.warning("Playwright not installed — cannot take screenshots")
            return False
        except Exception as e:
            logger.warning("Screenshot error for %s: %s", url, e)
            return False

    async def _try_browser_use(self, url: str, instruction: str) -> str | None:
        try:
            from browser_use import Agent
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(model="gpt-4o-mini", api_key=self.openai_api_key)
            agent = Agent(
                task=f"Go to {url}. {instruction} Return ONLY the extracted text, no commentary.",
                llm=llm,
            )
            result = await asyncio.wait_for(agent.run(), timeout=60)
            if result and isinstance(result, str) and len(result.strip()) > 100:
                return result.strip()
            return None
        except TimeoutError:
            logger.debug("Browser Use timed out for %s", url)
            return None
        except ImportError:
            logger.debug("browser-use not installed, skipping")
            return None
        except Exception as e:
            logger.debug("Browser Use error for %s: %s", url, e)
            return None

    async def _try_playwright_extract(self, url: str) -> str | None:
        """Basic text extraction using Playwright without LLM guidance."""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                ctx = await browser.new_context(
                    user_agent="Mozilla/5.0 (compatible; research-bot/1.0)"
                )
                page = await ctx.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    await page.wait_for_timeout(1500)
                    # Extract text from main content area
                    text = await page.evaluate(
                        """() => {
                        const selectors = ['main', 'article', '.content', '#content', 'body'];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el) return el.innerText;
                        }
                        return document.body.innerText;
                    }"""
                    )
                    return text if text and len(text) > 200 else None
                finally:
                    await browser.close()
        except ImportError:
            return None
        except Exception as e:
            logger.debug("Playwright extract error for %s: %s", url, e)
            return None
