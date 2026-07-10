"""
tools/url_prober.py
-------------------
HTTP HEAD request validator.
Used by Evidence Collector to verify that source URLs are reachable.
Results are cached to avoid redundant network calls.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# Module-level cache: url → (is_valid, status_code)
_probe_cache: dict[str, tuple[bool, int]] = {}


async def probe_url(
    url: str,
    timeout: float = 8.0,
    follow_redirects: bool = True,
) -> tuple[bool, int]:
    """
    Perform an HTTP HEAD request to verify a URL is reachable.

    Returns (is_valid, status_code).
    is_valid = True if status_code is 2xx or 3xx.
    Results are cached for the duration of the process.
    """
    if url in _probe_cache:
        return _probe_cache[url]

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=follow_redirects,
            headers={"User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)"},
        ) as client:
            resp = await client.head(url)
            valid = resp.status_code < 400
            result = (valid, resp.status_code)
            _probe_cache[url] = result
            return result
    except httpx.TimeoutException:
        logger.debug("URL probe timeout: %s", url)
        _probe_cache[url] = (False, 0)
        return False, 0
    except Exception as e:
        logger.debug("URL probe error for %s: %s", url, e)
        _probe_cache[url] = (False, 0)
        return False, 0


def clear_cache() -> None:
    """Clear the URL probe cache (useful in tests)."""
    _probe_cache.clear()
