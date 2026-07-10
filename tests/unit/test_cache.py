"""Tests for core/cache.py"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.cache import CacheEntry, DiskCache


class TestCacheEntry:
    def test_not_expired_within_ttl(self):
        entry = CacheEntry("content", time.time(), ttl_seconds=3600)
        assert entry.is_expired is False

    def test_expired_after_ttl(self):
        entry = CacheEntry("content", time.time() - 7200, ttl_seconds=3600)
        assert entry.is_expired is True

    def test_roundtrip_serialization(self):
        original = CacheEntry("hello", 1234567890.0, ttl_seconds=86400, status_code=200)
        restored = CacheEntry.from_dict(original.to_dict())
        assert restored.content == original.content
        assert restored.ttl_seconds == original.ttl_seconds
        assert restored.status_code == original.status_code


class TestDiskCache:
    def test_miss_returns_none(self, tmp_path):
        cache = DiskCache(tmp_path / "cache")
        assert cache.get("https://example.com") is None

    def test_set_and_get(self, tmp_path):
        cache = DiskCache(tmp_path / "cache", ttl_seconds=3600)
        cache.set("https://example.com", "hello world")
        entry = cache.get("https://example.com")
        assert entry is not None
        assert entry.content == "hello world"

    def test_expired_entry_returns_none(self, tmp_path):
        cache = DiskCache(tmp_path / "cache", ttl_seconds=1)
        cache.set("https://example.com", "stale content")
        # Manually expire by writing old timestamp
        import hashlib, json
        key = hashlib.sha256(b"https://example.com").hexdigest()
        path = tmp_path / "cache" / f"{key}.json"
        data = json.loads(path.read_text())
        data["fetched_at"] = time.time() - 10
        path.write_text(json.dumps(data))
        assert cache.get("https://example.com") is None

    def test_invalidate_removes_entry(self, tmp_path):
        cache = DiskCache(tmp_path / "cache")
        cache.set("https://example.com", "data")
        cache.invalidate("https://example.com")
        assert cache.get("https://example.com") is None

    def test_hit_ratio_tracking(self, tmp_path):
        cache = DiskCache(tmp_path / "cache", ttl_seconds=3600)
        cache.set("https://a.com", "a")
        cache.get("https://a.com")   # hit
        cache.get("https://b.com")   # miss
        assert cache._hits == 1
        assert cache._misses == 1
        assert cache.hit_ratio == 0.5

    def test_clear_expired_removes_stale(self, tmp_path):
        import hashlib, json
        cache = DiskCache(tmp_path / "cache", ttl_seconds=1)
        cache.set("https://stale.com", "stale")
        # Manually expire
        key = hashlib.sha256(b"https://stale.com").hexdigest()
        path = tmp_path / "cache" / f"{key}.json"
        data = json.loads(path.read_text())
        data["fetched_at"] = time.time() - 100
        path.write_text(json.dumps(data))
        removed = cache.clear_expired()
        assert removed == 1

    def test_stats_returns_dict(self, tmp_path):
        cache = DiskCache(tmp_path / "cache")
        stats = cache.stats
        assert "hits" in stats
        assert "hit_ratio" in stats

    def test_different_urls_different_keys(self, tmp_path):
        cache = DiskCache(tmp_path / "cache", ttl_seconds=3600)
        cache.set("https://a.com", "content A")
        cache.set("https://b.com", "content B")
        assert cache.get("https://a.com").content == "content A"
        assert cache.get("https://b.com").content == "content B"
