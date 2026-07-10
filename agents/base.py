"""
agents/base.py
--------------
Abstract base class for all research agents.
Provides: structured LLM output, retry logic, event logging, error handling.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from database.repository import AgentLogRepository

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AgentError(Exception):
    """Raised when an agent fails after all retries."""


class BaseAgent(ABC):
    """
    Abstract base for all research agents.

    Subclasses implement `_execute()` which contains the actual agent logic.
    `run()` wraps it with retry, logging, and error handling.
    """

    name: str = "base_agent"

    def __init__(
        self,
        log_repo: AgentLogRepository,
        session_id: str,
        max_retries: int = 3,
    ) -> None:
        self.log_repo = log_repo
        self.session_id = session_id
        self.max_retries = max_retries
        self._logger = logging.getLogger(f"agents.{self.name}")

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Public entry point. Wraps _execute() with retry and error handling.
        Returns updated state dict; raises AgentError on permanent failure.
        """
        app_id = state.get("app_id")
        app_name = state.get("app_name", "unknown")

        await self._log("agent_start", f"Starting {self.name} for {app_name}", app_id)

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                result = await self._execute(state)
                await self._log("agent_complete", f"{self.name} completed successfully", app_id)
                return result
            except AgentError:
                raise
            except Exception as exc:
                last_exc = exc
                self._logger.warning(
                    "%s attempt %d/%d failed for %s: %s",
                    self.name, attempt, self.max_retries, app_name, exc,
                )
                await self._log(
                    "agent_retry",
                    f"Attempt {attempt}/{self.max_retries} failed: {exc}",
                    app_id,
                    level="WARNING",
                    metadata={"attempt": attempt, "error": str(exc)},
                )

        await self._log(
            "agent_failure",
            f"{self.name} permanently failed after {self.max_retries} attempts: {last_exc}",
            app_id,
            level="ERROR",
        )
        raise AgentError(f"{self.name} failed: {last_exc}") from last_exc

    @abstractmethod
    async def _execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Agent-specific logic. Receives full state, returns updated state."""
        ...

    async def _log(
        self,
        event_type: str,
        message: str,
        app_id: int | None = None,
        level: str = "INFO",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write a structured log entry to SQLite and Python logger."""
        log_fn = getattr(self._logger, level.lower(), self._logger.info)
        log_fn("[%s] %s", event_type, message)
        try:
            await self.log_repo.log(
                session_id=self.session_id,
                agent_name=self.name,
                event_type=event_type,
                message=message,
                app_id=app_id,
                metadata=metadata,
                level=level,
            )
        except Exception as e:
            self._logger.warning("Failed to write log to DB: %s", e)
