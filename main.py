#!/usr/bin/env python3
"""
main.py
-------
CLI entry point for the Autonomous SaaS Research Platform.

Commands:
  run            Run the full research pipeline on a CSV input
  resume         Resume an interrupted session
  import-review  Apply human corrections from human_review.json
  export         Export DB to JSON
  report         Regenerate HTML report for a previous session
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

console = Console()


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging to stdout + rotating file."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    import logging.handlers

    handlers: list[logging.Handler] = [
        RichHandler(console=console, rich_tracebacks=True, show_path=False),
    ]
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "research.log",
        maxBytes=52_428_800,  # 50 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handlers.append(file_handler)

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=handlers,
        format="%(message)s",
        datefmt="[%X]",
    )
    # Quiet noisy libraries
    for lib in ["httpx", "httpcore", "openai", "firecrawl", "playwright", "langchain"]:
        logging.getLogger(lib).setLevel(logging.WARNING)


def check_env_vars() -> None:
    """Validate required env vars are set. Exit with helpful message if not."""
    from core.config import validate_required_env_vars

    missing = validate_required_env_vars()
    if missing:
        console.print(
            Panel(
                "[red]Missing required environment variables:[/red]\n"
                + "\n".join(f"  • {v}" for v in missing)
                + "\n\n[dim]Copy .env.example to .env and fill in the values.[/dim]",
                title="Configuration Error",
                border_style="red",
            )
        )
        sys.exit(1)


async def _run_pipeline(input_csv: str, resume: bool = False) -> None:
    """Core pipeline execution logic shared by 'run' and 'resume' commands."""
    from langchain_openai import ChatOpenAI

    from agents.api_analyzer import APIAnalyzerAgent
    from agents.auth_extractor import AuthExtractorAgent
    from agents.dev_portal import DevPortalAgent
    from agents.doc_finder import DocFinderAgent
    from agents.doc_parser import DocParserAgent
    from agents.evidence_collector import EvidenceCollectorAgent
    from agents.mcp_detector import MCPDetectorAgent
    from agents.tiebreaker import TiebreakerAgent
    from agents.verifier import VerifierAgent
    from core.cache import DiskCache
    from core.config import get_settings
    from core.exporter import DataExporter
    from core.ingestor import CSVIngestor
    from core.pattern_engine import PatternDiscoveryEngine
    from core.pipeline import ResearchPipeline
    from core.queue import TaskQueue
    from core.reporter import ReportGenerator
    from core.scheduler import Scheduler
    from core.session import SessionManager
    from database.connection import DatabaseManager
    from database.repository import (
        AgentLogRepository,
        AppRepository,
        EvidenceRepository,
        VerificationRepository,
    )

    settings = get_settings()

    async with DatabaseManager(settings.database_path) as conn:
        # ── Session ──────────────────────────────────────────────────────
        session_mgr = SessionManager(conn)
        if resume:
            session = await session_mgr.load_latest()
            if not session:
                console.print("[red]No session to resume. Run 'python main.py run' first.[/red]")
                return
            console.print(f"[yellow]Resuming session: {session.id[:8]}[/yellow]")
        else:
            config_snapshot = {
                "concurrency": settings.concurrency,
                "max_retries": settings.max_retries,
                "confidence_threshold": settings.confidence_threshold,
                "model_extraction": settings.openai_model_extraction,
                "model_classification": settings.openai_model_classification,
            }
            session = await session_mgr.create(config_snapshot)
            console.print(f"[green]New session: {session.id[:8]}[/green]")

        # ── Tool instances ───────────────────────────────────────────────
        cache = DiskCache(settings.cache_dir, settings.cache_ttl_seconds)
        log_repo = AgentLogRepository(conn)
        ev_repo = EvidenceRepository(conn)
        verif_repo = VerificationRepository(conn)
        app_repo = AppRepository(conn)

        llm_extract = ChatOpenAI(
            model=settings.openai_model_extraction,
            api_key=settings.openai_api_key,
            temperature=0,
        )
        llm_classify = ChatOpenAI(
            model=settings.openai_model_classification,
            api_key=settings.openai_api_key,
            temperature=0,
        )

        from tools.browser_client import BrowserClient
        from tools.firecrawl_client import FirecrawlClient
        from tools.search_client import SearchClient

        search = SearchClient(settings.tavily_api_key)
        firecrawl = FirecrawlClient(settings.firecrawl_api_key, cache)
        browser = BrowserClient(cache, settings.openai_api_key)

        # ── Agents ───────────────────────────────────────────────────────
        pipeline = ResearchPipeline(
            doc_finder=DocFinderAgent(search, log_repo, session.id),
            doc_parser=DocParserAgent(
                firecrawl, browser, log_repo, session.id, max_doc_pages=settings.max_doc_pages
            ),
            auth_extractor=AuthExtractorAgent(llm_extract, log_repo, session.id),
            api_analyzer=APIAnalyzerAgent(llm_extract, log_repo, session.id),
            dev_portal=DevPortalAgent(llm_classify, browser, search, log_repo, session.id),
            mcp_detector=MCPDetectorAgent(
                llm_classify, search, log_repo, session.id, github_token=settings.github_token
            ),
            evidence_collector=EvidenceCollectorAgent(ev_repo, log_repo, session.id),
            verifier=VerifierAgent(llm_extract, verif_repo, log_repo, session.id),
            tiebreaker=TiebreakerAgent(
                ChatOpenAI(
                    model=settings.model_tiebreaker, api_key=settings.openai_api_key, temperature=0
                ),
                log_repo,
                session.id,
            ),
            app_repo=app_repo,
            confidence_threshold=settings.confidence_threshold,
        )
        graph = pipeline.build()

        # ── Ingest ───────────────────────────────────────────────────────
        queue = TaskQueue(conn, session.id, settings.max_retries, settings.timeout_seconds)
        if not resume:
            ingestor = CSVIngestor(queue)
            result = await ingestor.ingest(input_csv)
            await session_mgr.update_counts(session.id, result.enqueued)
            if result.warnings:
                for w in result.warnings[:5]:
                    console.print(f"[yellow]⚠ {w}[/yellow]")
            console.print(f"\n[bold]{result.report()}[/bold]\n")

        # ── Run pipeline ─────────────────────────────────────────────────
        scheduler = Scheduler(
            queue=queue,
            app_repo=app_repo,
            run_pipeline=graph.ainvoke,
            concurrency=settings.concurrency,
            timeout_seconds=settings.timeout_seconds,
        )
        completed, failed = await scheduler.run_all()

        # ── Pattern discovery ─────────────────────────────────────────────
        console.print("\n[bold cyan]Running pattern discovery engine...[/bold cyan]")
        engine = PatternDiscoveryEngine(conn, session.id)
        statistics = await engine.run()

        # Save statistics
        Path("data/exports").mkdir(parents=True, exist_ok=True)
        stats_path = Path("data/exports/statistics.json")
        stats_path.write_text(json.dumps(statistics, indent=2, default=str))

        # ── Export ────────────────────────────────────────────────────────
        exporter = DataExporter(conn, session.id)
        export_paths = await exporter.export_all()

        # ── Finalize session ──────────────────────────────────────────────
        confidences = [a.confidence_score for a in await app_repo.get_all_verified(session.id)]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        await session_mgr.finalize(
            session_id=session.id,
            completed_apps=completed,
            failed_apps=failed,
            avg_confidence=avg_conf,
            human_review_count=statistics.get("human_review_count", 0),
            total_api_calls=0,
            cache_hit_ratio=cache.hit_ratio,
            estimated_cost_usd=0.0,
        )

        # ── Generate HTML report ──────────────────────────────────────────
        console.print("[bold cyan]Generating HTML report...[/bold cyan]")
        reporter = ReportGenerator(conn, session.id)
        report_path = await reporter.generate(statistics)

        # ── Summary ───────────────────────────────────────────────────────
        summary_table = Table(title="Run Complete", show_header=False, padding=(0, 2))
        summary_table.add_row("Session", session.id[:8])
        summary_table.add_row("Completed", str(completed))
        summary_table.add_row("Failed", str(failed))
        summary_table.add_row("Avg Confidence", f"{avg_conf*100:.1f}%")
        summary_table.add_row("Cache Hit Ratio", f"{cache.hit_ratio*100:.1f}%")
        summary_table.add_row("Report", report_path)
        summary_table.add_row("Human Review", export_paths.get("human_review", ""))
        summary_table.add_row("Data Export", export_paths.get("data_export", ""))
        console.print(summary_table)


# ── CLI Commands ──────────────────────────────────────────────────────────


@click.group()
@click.option("--log-level", default="INFO", help="Logging level")
def cli(log_level: str) -> None:
    """Autonomous SaaS Research Platform"""
    load_dotenv()
    setup_logging(log_level)


@cli.command()
@click.option("--input", "input_csv", default="data/apps.csv", help="Path to apps.csv")
def run(input_csv: str) -> None:
    """Run the full research pipeline."""
    check_env_vars()
    console.print(
        Panel(
            "[bold green]SaaS Research Platform[/bold green]\nStarting research run...",
            border_style="green",
        )
    )
    asyncio.run(_run_pipeline(input_csv, resume=False))


@cli.command()
def resume() -> None:
    """Resume the most recent interrupted session."""
    check_env_vars()
    console.print("[yellow]Resuming last session...[/yellow]")
    asyncio.run(_run_pipeline("data/apps.csv", resume=True))


@cli.command("import-review")
@click.option(
    "--file",
    "review_file",
    default="data/exports/human_review.json",
    help="Path to human_review.json",
)
def import_review(review_file: str) -> None:
    """Apply human corrections from human_review.json."""
    check_env_vars()

    async def _import() -> None:
        from core.config import get_settings
        from core.exporter import DataExporter
        from database.connection import DatabaseManager

        settings = get_settings()
        async with DatabaseManager(settings.database_path) as conn:
            from core.session import SessionManager

            session = await SessionManager(conn).load_latest()
            if not session:
                console.print("[red]No session found.[/red]")
                return
            exporter = DataExporter(conn, session.id)
            count = await exporter.import_human_review(review_file)
            console.print(f"[green]Imported {count} corrections from {review_file}[/green]")

            # Regenerate report
            from core.pattern_engine import PatternDiscoveryEngine
            from core.reporter import ReportGenerator

            engine = PatternDiscoveryEngine(conn, session.id)
            statistics = await engine.run()
            reporter = ReportGenerator(conn, session.id)
            path = await reporter.generate(statistics)
            console.print(f"[green]Report regenerated: {path}[/green]")

    asyncio.run(_import())


@cli.command()
@click.option("--session", "session_id", default=None, help="Session UUID (default: latest)")
def report(session_id: str | None) -> None:
    """Regenerate HTML report for a session without re-running research."""

    async def _report() -> None:
        from core.config import get_settings
        from core.pattern_engine import PatternDiscoveryEngine
        from core.reporter import ReportGenerator
        from core.session import SessionManager
        from database.connection import DatabaseManager

        settings = get_settings()
        async with DatabaseManager(settings.database_path) as conn:
            mgr = SessionManager(conn)
            session = await (mgr.load(session_id) if session_id else mgr.load_latest())
            if not session:
                console.print("[red]No session found.[/red]")
                return
            engine = PatternDiscoveryEngine(conn, session.id)
            statistics = await engine.run()
            reporter = ReportGenerator(conn, session.id)
            path = await reporter.generate(statistics)
            console.print(f"[green]Report generated: {path}[/green]")

    asyncio.run(_report())


@cli.command()
@click.option("--session", "session_id", default=None)
def export(session_id: str | None) -> None:
    """Export database to JSON files."""

    async def _export() -> None:
        from core.config import get_settings
        from core.exporter import DataExporter
        from core.session import SessionManager
        from database.connection import DatabaseManager

        settings = get_settings()
        async with DatabaseManager(settings.database_path) as conn:
            mgr = SessionManager(conn)
            session = await (mgr.load(session_id) if session_id else mgr.load_latest())
            if not session:
                console.print("[red]No session found.[/red]")
                return
            exporter = DataExporter(conn, session.id)
            paths = await exporter.export_all()
            for k, v in paths.items():
                console.print(f"[green]{k}:[/green] {v}")

    asyncio.run(_export())


if __name__ == "__main__":
    cli()
