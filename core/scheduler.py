"""
core/scheduler.py
-----------------
Async semaphore-based concurrent scheduler.
Processes apps from the queue up to `concurrency` at a time.
Enforces per-app timeouts and drives the LangGraph pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn

from core.queue import QueueStats, TaskQueue
from database.models import AppRecord
from database.repository import AppRepository

logger = logging.getLogger(__name__)
console = Console()


class Scheduler:
    def __init__(
        self,
        queue: TaskQueue,
        app_repo: AppRepository,
        run_pipeline: Callable[[dict[str, Any]], Any],
        concurrency: int = 5,
        timeout_seconds: int = 120,
    ) -> None:
        self.queue = queue
        self.app_repo = app_repo
        self.run_pipeline = run_pipeline
        self.concurrency = concurrency
        self.timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(concurrency)
        self._completed = 0
        self._failed = 0

    async def run_all(self) -> tuple[int, int]:
        """
        Process all pending apps concurrently.
        Returns (completed_count, failed_count).
        """
        # First, restore any orphaned in-progress apps
        restored = await self.queue.restore_orphaned()
        if restored:
            console.print(f"[yellow]Restored {restored} orphaned apps to pending[/yellow]")

        stats = await self.queue.get_stats()
        total = stats.pending + stats.in_progress
        console.print(f"[green]Processing {total} apps (concurrency={self.concurrency})[/green]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as progress:
            task_id = progress.add_task("Researching apps...", total=total)

            async def process_one(app: AppRecord) -> None:
                async with self._semaphore:
                    await self._process_app(app, progress, task_id)

            # Feed tasks as queue is consumed
            tasks: list[asyncio.Task] = []
            while not await self.queue.is_complete():
                app = await self.queue.claim_next()
                if app is None:
                    # Wait for in-progress tasks to complete
                    if tasks:
                        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        tasks = list(pending)
                    else:
                        await asyncio.sleep(0.5)
                    continue

                t = asyncio.create_task(process_one(app))
                tasks.append(t)

            # Wait for remaining tasks
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        return self._completed, self._failed

    async def _process_app(
        self,
        app: AppRecord,
        progress: Progress,
        task_id: Any,
    ) -> None:
        """Process a single app through the full pipeline with timeout."""
        start = time.monotonic()
        try:
            initial_state: dict[str, Any] = {
                "app_id": app.id,
                "app_name": app.app_name,
                "seed_url": app.seed_url,
                "session_id": app.session_id,
                "human_review_required": False,
            }

            await asyncio.wait_for(
                self.run_pipeline(initial_state),
                timeout=self.timeout_seconds,
            )

            await self.queue.complete(app.id)  # type: ignore[arg-type]
            self._completed += 1
            elapsed = time.monotonic() - start
            logger.info("✓ %s completed in %.1fs", app.app_name, elapsed)

        except asyncio.TimeoutError:
            error = f"Timed out after {self.timeout_seconds}s"
            logger.warning("⏱ %s timed out", app.app_name)
            await self.queue.fail(app.id, error)  # type: ignore[arg-type]
            self._failed += 1

        except Exception as e:
            error = str(e)[:500]
            logger.error("✗ %s failed: %s", app.app_name, error)
            await self.queue.fail(app.id, error)  # type: ignore[arg-type]
            self._failed += 1

        finally:
            progress.advance(task_id)
