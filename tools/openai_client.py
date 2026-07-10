"""
tools/openai_client.py
----------------------
OpenAI structured output helpers.
Provides token counting and cost estimation utilities.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Approximate cost per 1M tokens (USD) as of 2025
_COST_TABLE: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
}


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate USD cost for a single LLM call."""
    prices = _COST_TABLE.get(model, _COST_TABLE["gpt-4o"])
    cost = (input_tokens / 1_000_000) * prices["input"]
    cost += (output_tokens / 1_000_000) * prices["output"]
    return round(cost, 6)


def count_tokens_approx(text: str) -> int:
    """
    Rough token count estimate (4 chars per token).
    Use tiktoken for precise counts when cost accuracy matters.
    """
    return max(1, len(text) // 4)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximately max_tokens tokens."""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars]
