"""
agents/doc_parser.py
--------------------
Documentation parsing agent.
Fetches documentation pages via Firecrawl (with Browser Use fallback),
discovers relevant subpages, and chunks content for downstream agents.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from agents.base import BaseAgent
from database.repository import AgentLogRepository
from tools.firecrawl_client import FirecrawlClient
from tools.browser_client import BrowserClient


# Subpage path patterns worth crawling for API research
RELEVANT_SUBPAGE_PATTERNS = re.compile(
    r"/(auth(?:entication)?|api[-_]?ref(?:erence)?|api|reference|getting[-_]?started"
    r"|quickstart|oauth|pricing|developers?|rest|graphql|webhook|rate[-_]?limit)",
    re.IGNORECASE,
)


class ContentChunk:
    __slots__ = ("content", "source_url", "chunk_index", "token_count")

    def __init__(self, content: str, source_url: str, chunk_index: int, token_count: int) -> None:
        self.content = content
        self.source_url = source_url
        self.chunk_index = chunk_index
        self.token_count = token_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "source_url": self.source_url,
            "chunk_index": self.chunk_index,
            "token_count": self.token_count,
        }


class DocParserAgent(BaseAgent):
    name = "doc_parser"

    def __init__(
        self,
        firecrawl: FirecrawlClient,
        browser: BrowserClient,
        log_repo: AgentLogRepository,
        session_id: str,
        max_doc_pages: int = 20,
        max_doc_depth: int = 3,
        max_retries: int = 3,
    ) -> None:
        super().__init__(log_repo, session_id, max_retries)
        self.firecrawl = firecrawl
        self.browser = browser
        self.max_doc_pages = max_doc_pages
        self.max_doc_depth = max_doc_depth

    async def _execute(self, state: dict[str, Any]) -> dict[str, Any]:
        doc_url: str | None = state.get("documentation_url")
        app_id: int | None = state.get("app_id")
        app_name: str = state.get("app_name", "unknown")

        if not doc_url:
            await self._log("skip", "No documentation URL — skipping parse", app_id, level="WARNING")
            return {**state, "chunks": [], "pages_parsed": 0, "parse_method": "skipped"}

        # ── Step 1: Crawl the root documentation page ─────────────────────
        root_content, parse_method = await self._fetch_page(doc_url)
        if not root_content:
            await self._log("parse_failed", f"Could not extract content from {doc_url}", app_id, level="WARNING")
            return {**state, "chunks": [], "pages_parsed": 0, "parse_method": "failed"}

        # ── Step 2: Discover relevant subpage links ───────────────────────
        subpage_urls = self._extract_relevant_links(root_content, doc_url)
        await self._log(
            "subpages_found",
            f"Found {len(subpage_urls)} relevant subpages",
            app_id,
            metadata={"subpages": subpage_urls[:10]},
        )

        # ── Step 3: Crawl subpages (BFS, limited) ────────────────────────
        all_pages: list[tuple[str, str]] = [(doc_url, root_content)]
        visited = {doc_url}

        for subpage_url in subpage_urls[: self.max_doc_pages - 1]:
            if subpage_url in visited:
                continue
            content, _ = await self._fetch_page(subpage_url)
            if content:
                all_pages.append((subpage_url, content))
            visited.add(subpage_url)

        # ── Step 4: Chunk all content ─────────────────────────────────────
        chunks: list[ContentChunk] = []
        chunk_idx = 0
        for page_url, page_content in all_pages:
            page_chunks = self._chunk_content(page_content, page_url, start_index=chunk_idx)
            chunks.extend(page_chunks)
            chunk_idx += len(page_chunks)

        # ── Step 5: Store raw combined markdown ───────────────────────────
        raw_markdown = "\n\n---\n\n".join(f"<!-- SOURCE: {u} -->\n{c}" for u, c in all_pages)

        await self._log(
            "parse_complete",
            f"Parsed {len(all_pages)} pages into {len(chunks)} chunks for {app_name}",
            app_id,
            metadata={"pages": len(all_pages), "chunks": len(chunks), "method": parse_method},
        )

        return {
            **state,
            "chunks": [c.to_dict() for c in chunks],
            "pages_parsed": len(all_pages),
            "parse_method": parse_method,
            "raw_markdown": raw_markdown[:500_000],  # cap for DB storage
        }

    async def _fetch_page(self, url: str) -> tuple[str | None, str]:
        """Fetch a page using Firecrawl, falling back to Browser Use on failure."""
        try:
            content = await self.firecrawl.scrape(url)
            if content and len(content.strip()) > 200:
                return content, "firecrawl"
        except Exception as e:
            self._logger.debug("Firecrawl failed for %s: %s — trying browser", url, e)

        try:
            content = await self.browser.extract_markdown(url)
            if content and len(content.strip()) > 200:
                return content, "browser_use"
        except Exception as e:
            self._logger.warning("Browser Use also failed for %s: %s", url, e)

        return None, "failed"

    def _extract_relevant_links(self, markdown: str, base_url: str) -> list[str]:
        """Extract links from markdown that match relevant documentation patterns."""
        base_domain = urlparse(base_url).netloc
        # Match markdown links: [text](url) or bare URLs
        link_pattern = re.compile(r'\[.*?\]\((https?://[^\s)]+)\)|href=["\']([^"\']+)["\']')
        found: list[str] = []
        for m in link_pattern.finditer(markdown):
            raw = m.group(1) or m.group(2)
            if not raw:
                continue
            # Make absolute if relative
            if raw.startswith("/"):
                raw = f"{urlparse(base_url).scheme}://{base_domain}{raw}"
            if urlparse(raw).netloc != base_domain:
                continue
            if RELEVANT_SUBPAGE_PATTERNS.search(urlparse(raw).path):
                found.append(raw.split("#")[0])  # strip fragment
        # Deduplicate preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for u in found:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        return unique[: self.max_doc_pages]

    def _chunk_content(
        self,
        content: str,
        source_url: str,
        start_index: int = 0,
        max_chars: int = 32_000,
        overlap_chars: int = 800,
    ) -> list[ContentChunk]:
        """
        Split content into overlapping chunks at paragraph boundaries.
        max_chars ~ 8000 tokens at ~4 chars/token.
        """
        paragraphs = re.split(r"\n{2,}", content)
        chunks: list[ContentChunk] = []
        current_parts: list[str] = []
        current_len = 0
        idx = start_index

        for para in paragraphs:
            para_len = len(para)
            if current_len + para_len > max_chars and current_parts:
                chunk_text = "\n\n".join(current_parts)
                chunks.append(ContentChunk(
                    content=chunk_text,
                    source_url=source_url,
                    chunk_index=idx,
                    token_count=len(chunk_text) // 4,
                ))
                idx += 1
                # Keep last overlap portion
                overlap_text = chunk_text[-overlap_chars:] if len(chunk_text) > overlap_chars else chunk_text
                current_parts = [overlap_text]
                current_len = len(overlap_text)

            current_parts.append(para)
            current_len += para_len + 2

        if current_parts:
            chunk_text = "\n\n".join(current_parts)
            if chunk_text.strip():
                chunks.append(ContentChunk(
                    content=chunk_text,
                    source_url=source_url,
                    chunk_index=idx,
                    token_count=len(chunk_text) // 4,
                ))

        return chunks
