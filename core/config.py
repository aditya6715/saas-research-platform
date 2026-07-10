"""
core/config.py
--------------
Single source of truth for all configuration.
Merges .env file + environment variables + config.yaml.
Uses Pydantic Settings for type-safe access.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Required API Keys ──────────────────────────────────────────────
    openai_api_key: str = Field(..., description="OpenAI API key")
    firecrawl_api_key: str = Field(..., description="Firecrawl API key")
    tavily_api_key: str = Field(..., description="Tavily search API key")

    # ── Optional Keys ──────────────────────────────────────────────────
    github_token: str | None = Field(None, description="GitHub PAT for search")

    # ── Model Selection ────────────────────────────────────────────────
    openai_model_extraction: str = Field("gpt-4o", description="Model for extraction")
    openai_model_classification: str = Field("gpt-4o-mini", description="Model for classification")

    # ── Paths ──────────────────────────────────────────────────────────
    database_path: str = Field("data/research.db", description="SQLite DB path")
    cache_dir: str = Field("data/cache", description="Disk cache directory")
    reports_dir: str = Field("reports", description="HTML reports output directory")
    log_level: str = Field("INFO", description="Logging level")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}")
        return upper

    # ── Pipeline params (from config.yaml, not env) ────────────────────
    # These are populated by load_settings() after reading config.yaml
    concurrency: int = 5
    max_retries: int = 3
    timeout_seconds: int = 120
    confidence_threshold: float = 0.85
    max_doc_pages: int = 20
    max_doc_depth: int = 3
    cache_ttl_seconds: int = 86400
    cache_enabled: bool = True
    min_inter_request_delay: float = 1.0
    backoff_initial: float = 5.0
    backoff_max: float = 120.0
    backoff_multiplier: float = 2.0
    max_tokens: int = 4096
    model_tiebreaker: str = "gpt-4o"
    easy_wins_count: int = 10
    easy_wins_min_confidence: float = 0.85


def _merge_yaml_into_settings(settings: Settings, yaml_path: Path) -> None:
    """Overlay config.yaml values onto already-initialized settings object."""
    if not yaml_path.exists():
        return
    with open(yaml_path) as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}

    pipeline = cfg.get("pipeline", {})
    models = cfg.get("models", {})
    cache = cfg.get("cache", {})
    rate = cfg.get("rate_limits", {})
    logging_cfg = cfg.get("logging", {})
    output = cfg.get("output", {})

    overrides = {
        "concurrency": pipeline.get("concurrency", settings.concurrency),
        "max_retries": pipeline.get("max_retries", settings.max_retries),
        "timeout_seconds": pipeline.get("timeout_seconds", settings.timeout_seconds),
        "confidence_threshold": pipeline.get("confidence_threshold", settings.confidence_threshold),
        "max_doc_pages": pipeline.get("max_doc_pages", settings.max_doc_pages),
        "max_doc_depth": pipeline.get("max_doc_depth", settings.max_doc_depth),
        "openai_model_extraction": models.get("extraction", settings.openai_model_extraction),
        "openai_model_classification": models.get("classification", settings.openai_model_classification),
        "model_tiebreaker": models.get("tiebreaker", settings.model_tiebreaker),
        "max_tokens": models.get("max_tokens", settings.max_tokens),
        "cache_ttl_seconds": cache.get("ttl_seconds", settings.cache_ttl_seconds),
        "cache_enabled": cache.get("enabled", settings.cache_enabled),
        "min_inter_request_delay": rate.get("min_inter_request_delay", settings.min_inter_request_delay),
        "backoff_initial": rate.get("backoff_initial", settings.backoff_initial),
        "backoff_max": rate.get("backoff_max", settings.backoff_max),
        "backoff_multiplier": rate.get("backoff_multiplier", settings.backoff_multiplier),
        "log_level": logging_cfg.get("level", settings.log_level).upper(),
        "easy_wins_count": output.get("easy_wins_count", settings.easy_wins_count),
        "easy_wins_min_confidence": output.get("easy_wins_min_confidence", settings.easy_wins_min_confidence),
    }
    # Use object.__setattr__ to bypass Pydantic's immutability for patching
    for k, v in overrides.items():
        object.__setattr__(settings, k, v)


@lru_cache(maxsize=1)
def get_settings(config_yaml: str = "config.yaml") -> Settings:
    """Load and cache settings. config_yaml path is baked into cache key."""
    s = Settings()  # type: ignore[call-arg]
    _merge_yaml_into_settings(s, Path(config_yaml))
    return s


def validate_required_env_vars() -> list[str]:
    """Return list of missing required env var names (empty = all good)."""
    required = ["OPENAI_API_KEY", "FIRECRAWL_API_KEY", "TAVILY_API_KEY"]
    return [k for k in required if not os.environ.get(k)]
