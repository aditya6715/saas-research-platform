"""
core/cache.py
-------------
Disk-based HTTP response cache with TTL.
Keys are SHA256 hashes of the URL.
Metadata sidecars track fetch time and TTL.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class CacheEntry:
    __slots__ = ("content", "fetched_at", "ttl_seconds", "status_code", "content_type")

    def __init__(
        self,
        content: str,
        fetched_at: float,
        ttl_seconds: int,
        status_code: int = 200,
        content_type: str = "text/plain",
    ) -> None:
        self.content = content
        self.fetched_at = fetched_at
        self.ttl_seconds = ttl_seconds
        self.status_code = status_code
        self.content_type = content_type

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.fetched_at) > self.ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "fetched_at": self.fetched_at,
            "ttl_seconds": self.ttl_seconds,
            "status_code": self.status_code,
            "content_type": self.content_type,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CacheEntry":
        return cls(
            content=d["content"],
            fetched_at=d["fetched_at"],
            ttl_seconds=d["ttl_seconds"],
            status_code=d.get("status_code", 200),
            content_type=d.get("content_type", "text/plain"),
        )


class DiskCache:
    """
    Thread-safe (single-process) disk cache.
    Each entry is stored as a JSON file named by SHA256(url).
    """

    def __init__(self, cache_dir: str | Path, ttl_seconds: int = 86400) -> None:
        self.cache_dir = Path(cache_dir)
        self.default_ttl = ttl_seconds
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0

    def _key(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()

    def _path(self, url: str) -> Path:
        return self.cache_dir / f"{self._key(url)}.json"

    def get(self, url: str) -> CacheEntry | None:
        path = self._path(url)
        if not path.exists():
            self._misses += 1
            return None
        try:
            entry = CacheEntry.from_dict(json.loads(path.read_text()))
            if entry.is_expired:
                path.unlink(missing_ok=True)
                self._misses += 1
                return None
            self._hits += 1
            return entry
        except (json.JSONDecodeError, KeyError):
            path.unlink(missing_ok=True)
            self._misses += 1
            return None

    def set(
        self,
        url: str,
        content: str,
        status_code: int = 200,
        content_type: str = "text/plain",
        ttl_seconds: int | None = None,
    ) -> None:
        entry = CacheEntry(
            content=content,
            fetched_at=time.time(),
            ttl_seconds=ttl_seconds if ttl_seconds is not None else self.default_ttl,
            status_code=status_code,
            content_type=content_type,
        )
        self._path(url).write_text(json.dumps(entry.to_dict(), ensure_ascii=False))

    def invalidate(self, url: str) -> None:
        self._path(url).unlink(missing_ok=True)

    def clear_expired(self) -> int:
        """Remove all expired entries. Returns count of removed files."""
        removed = 0
        for p in self.cache_dir.glob("*.json"):
            try:
                entry = CacheEntry.from_dict(json.loads(p.read_text()))
                if entry.is_expired:
                    p.unlink()
                    removed += 1
            except Exception:
                p.unlink(missing_ok=True)
                removed += 1
        return removed

    @property
    def hit_ratio(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_ratio": round(self.hit_ratio, 3),
            "cache_dir": str(self.cache_dir),
        }
