# SaaS Integration Research Platform

> Autonomous multi-agent pipeline that researches 100+ SaaS applications and produces a polished, interactive HTML report with verification-backed data.

Built as a production-grade demonstration of AI agent orchestration, multi-source verification, and structured data extraction at scale.

---

## What It Does

The platform takes a list of SaaS application names and autonomously:

1. **Discovers** the official developer documentation URL for each app
2. **Parses** documentation pages via Firecrawl (with Browser Use fallback)
3. **Extracts** in parallel: authentication methods, API surface type, access model, MCP support
4. **Verifies** every field with an independent second pass and cross-source comparison
5. **Scores** confidence per-field using a weighted formula (not vibes)
6. **Flags** low-confidence records for human review
7. **Discovers patterns** across all apps (MCP gap, easy wins, top blockers)
8. **Generates** a self-contained interactive HTML report

---

## Architecture

```
CSV Input → Ingestion → Queue → LangGraph Pipeline (per app)
                                    ├── Doc Finder (web search + URL scoring)
                                    ├── Doc Parser (Firecrawl → Browser Use)
                                    ├── Auth Extractor     ┐
                                    ├── API Analyzer       ├── parallel
                                    ├── Dev Portal Agent   ┘
                                    ├── MCP Detector
                                    ├── Evidence Collector
                                    ├── Verification Agent (2nd pass)
                                    ├── Tiebreaker Agent   (on disagreement)
                                    └── Confidence Scorer
                                         ↓
                                    SQLite DB
                                         ↓
                             Pattern Discovery Engine
                                         ↓
                              Jinja2 HTML Report Generator
                                         ↓
                              report_{session_id}.html
```

**Verification accuracy progression:**

| Stage | Mechanism | Target |
|-------|-----------|--------|
| Initial extraction | Single-pass GPT-4o | ~78% |
| Parallel extraction | 4 specialized agents | ~84% |
| Cross-source verification | Pass A vs B agreement | ~91% |
| Browser verification | Playwright portal check | ~95% |
| Human review | Manual correction | ~99% |

---

## Prerequisites

- Python 3.11+
- API keys for: [OpenAI](https://platform.openai.com), [Firecrawl](https://firecrawl.dev), [Tavily](https://tavily.com)
- (Optional) [GitHub PAT](https://github.com/settings/tokens) for MCP detection rate limits

---

## Quickstart

```bash
# 1. Clone
git clone https://github.com/yourname/saas-research-platform
cd saas-research-platform

# 2. Set up virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 4. Configure environment
cp .env.example .env
# Edit .env and add your API keys

# 5. Generate sample input (100 apps)
python scripts/seed_apps.py

# 6. Run the pipeline
python main.py run --input data/apps.csv

# 7. Open the report
open reports/report_*.html
```

---

## Docker

```bash
# Build and run
docker-compose up --build

# Reports will appear in ./reports/ (volume mounted)
```

---

## CLI Commands

```bash
# Run full pipeline
python main.py run --input data/apps.csv

# Resume interrupted session
python main.py resume

# Apply human corrections
python main.py import-review --file data/exports/human_review.json

# Regenerate report without re-running research
python main.py report

# Export data to JSON
python main.py export

# All commands support --log-level DEBUG/INFO/WARNING
python main.py --log-level DEBUG run
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | ✅ | OpenAI API key (GPT-4o for extraction) |
| `FIRECRAWL_API_KEY` | ✅ | Firecrawl API key for documentation parsing |
| `TAVILY_API_KEY` | ✅ | Tavily search API key for discovery |
| `GITHUB_TOKEN` | ☐ | GitHub PAT for MCP detection (increases rate limit 60→5000/hr) |
| `OPENAI_MODEL_EXTRACTION` | ☐ | Override extraction model (default: `gpt-4o`) |
| `OPENAI_MODEL_CLASSIFICATION` | ☐ | Override classification model (default: `gpt-4o-mini`) |
| `LOG_LEVEL` | ☐ | Logging level (default: `INFO`) |
| `DATABASE_PATH` | ☐ | SQLite DB path (default: `data/research.db`) |

---

## Configuration (`config.yaml`)

```yaml
pipeline:
  concurrency: 5          # Apps processed simultaneously
  max_retries: 3          # Per-app retry limit
  timeout_seconds: 120    # Per-app timeout
  confidence_threshold: 0.85  # Below this → human review flagged

models:
  extraction: gpt-4o
  classification: gpt-4o-mini
  tiebreaker: gpt-4o

cache:
  ttl_seconds: 86400      # 24-hour response cache
  enabled: true
```

---

## Output Files

After a successful run:

| File | Description |
|------|-------------|
| `reports/report_{id}.html` | Interactive HTML report (open in browser) |
| `data/exports/data_export_{id}.json` | Full structured JSON export with evidence |
| `data/exports/human_review.json` | Records flagged for human review |
| `data/exports/statistics.json` | Aggregate statistics and insights |
| `data/exports/run_summary.json` | Session-level metrics |
| `logs/research.log` | Full structured pipeline log |

---

## Human Review Workflow

When the pipeline flags records with low confidence:

```bash
# 1. Open the review file
open data/exports/human_review.json

# 2. Edit flagged fields, add your name:
# {
#   "app_name": "Salesforce",
#   "access_model": "Gated",   ← correct the value
#   "reviewer_name": "alice",  ← required
#   "review_notes": "Verified via enterprise sales page"
# }

# 3. Import corrections and regenerate report
python main.py import-review --file data/exports/human_review.json
```

Reviewed fields are shown with a ✓ badge in the HTML report.

---

## Project Structure

```
saas-research-platform/
├── main.py              # CLI entry point
├── config.yaml          # Pipeline configuration
├── .env.example         # Environment variable template
├── Dockerfile           # Container image
├── docker-compose.yml   # Compose with volume mounts
├── requirements.txt     # Pinned Python dependencies
├── pyproject.toml       # Ruff + black + pytest config
│
├── core/                # Orchestration (no LLM calls)
│   ├── config.py        # Settings (env + yaml)
│   ├── pipeline.py      # LangGraph StateGraph
│   ├── queue.py         # SQLite-backed task queue
│   ├── scheduler.py     # Async concurrency manager
│   ├── session.py       # Session lifecycle
│   ├── ingestor.py      # CSV ingestion
│   ├── confidence.py    # Scoring formulas
│   ├── buildability.py  # Verdict rule engine
│   ├── cache.py         # Disk cache (TTL)
│   ├── pattern_engine.py# Aggregate analytics
│   ├── reporter.py      # HTML report generator
│   └── exporter.py      # JSON exports
│
├── agents/              # LLM-backed research units
│   ├── base.py          # Abstract: retry, logging
│   ├── doc_finder.py    # Documentation URL discovery
│   ├── doc_parser.py    # Page crawling + chunking
│   ├── auth_extractor.py# Auth method identification
│   ├── api_analyzer.py  # API surface classification
│   ├── dev_portal.py    # Self-Serve/Gated detection
│   ├── mcp_detector.py  # MCP support search
│   ├── evidence_collector.py  # Evidence consolidation
│   ├── verifier.py      # Independent 2nd pass
│   └── tiebreaker.py    # Disagreement resolution
│
├── tools/               # External API wrappers
│   ├── firecrawl_client.py
│   ├── browser_client.py
│   ├── search_client.py
│   └── url_prober.py
│
├── database/            # Persistence layer
│   ├── connection.py    # aiosqlite + WAL + migrations
│   ├── models.py        # Pydantic data models
│   ├── repository.py    # All SQL queries
│   └── migrations/      # Sequential SQL migration files
│
├── templates/           # Jinja2 HTML templates
│   ├── base.html        # Layout + CDN imports
│   ├── report.html      # Master template
│   ├── summary.html     # Hero section
│   ├── metrics.html     # Key metric cards
│   ├── charts.html      # Chart.js visualizations
│   ├── insights.html    # Pattern narratives
│   ├── table.html       # Searchable data table
│   ├── table_scripts.html # Filter/sort/expand JS
│   └── architecture.html  # Mermaid diagrams
│
├── tests/
│   ├── conftest.py      # Shared fixtures
│   ├── unit/            # Fast, no-network tests
│   └── integration/     # Full pipeline (mocked APIs)
│
└── scripts/
    ├── seed_apps.py     # Generate 100-app CSV
    ├── validate_report.py  # HTML smoke tests
    ├── export_data.py   # JSON export CLI
    └── import_review.py # Apply human corrections
```

---

## Running Tests

```bash
# Unit tests (fast, no API keys needed)
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# All tests with coverage
pytest --cov=core --cov=agents --cov=database --cov-report=html
open htmlcov/index.html

# Single test file
pytest tests/unit/test_confidence.py -v
```

---

## Design Decisions

**Why LangGraph?**
Models the workflow as an explicit directed graph. Every state transition is visible and debuggable. Supports conditional edges (e.g., skip tiebreaker if agents agree), crash recovery via checkpointing, and clean parallel node execution.

**Why Firecrawl over BeautifulSoup?**
Documentation sites are JavaScript-rendered SPAs (Next.js, Docusaurus). BeautifulSoup operates on static HTML and returns empty content. Firecrawl handles rendering, strips navigation/footer noise, and returns clean markdown.

**Why Browser Use for portal verification?**
Determining whether a signup flow is truly self-serve requires navigating a developer portal dynamically — clicking buttons, reading modal content. Browser Use wraps Playwright with LLM guidance for natural-language navigation instructions.

**Why SQLite over Postgres?**
Zero ops overhead for a research tool. A single file is easy to copy, inspect, and version. WAL mode handles the concurrent writes from 5 parallel agents comfortably. Migrate to Postgres only when multi-user or multi-process concurrency is needed.

**Why HTML over React?**
The report is a document, not an application. A self-contained HTML file opens in any browser, requires no build step, and can be emailed or hosted on GitHub Pages. All interactivity (charts, search, dark mode) is achievable with Chart.js + vanilla JavaScript + Tailwind CDN.

**Why confidence scores?**
LLMs hallucinate. A field value without a score is indistinguishable from a certain extraction and a guess. Confidence scores make reliability explicit, enable automated human review flagging, and allow downstream systems to decide whether to trust a value.

---

## Tech Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Language | Python 3.11 | Entire AI/agent ecosystem is Python-native |
| Agent Orchestration | LangGraph | Explicit graph, stateful, resumable |
| Web Crawling | Firecrawl | Handles JS-rendered docs, returns clean markdown |
| Browser Automation | Browser Use + Playwright | LLM-guided navigation for portal verification |
| Web Search | Tavily | Structured search results with relevance scores |
| LLM | GPT-4o / GPT-4o-mini | Best structured output accuracy; mini for cost |
| Database | SQLite (WAL) | Zero-ops, single file, handles concurrent writes |
| Data Validation | Pydantic v2 | Strict schemas, JSON schema for LLM output |
| Templates | Jinja2 | Standard Python templating, no build step |
| Charts | Chart.js | CDN-deliverable, interactive, well-documented |
| Diagrams | Mermaid.js | Rendered client-side from markdown |
| Styling | Tailwind CSS | CDN play build, dark mode, no build required |
| CLI | Click | Clean command interface with groups |
| Retry Logic | Tenacity | Configurable retry/backoff strategies |
| Terminal UI | Rich | Progress bars, structured tables, color output |
| Linting | Ruff + Black | Fast, consistent, minimal config |
| Testing | Pytest + pytest-asyncio | Async-native test runner |
| CI/CD | GitHub Actions | Lint + unit + integration + Docker build |

---

## License

MIT
