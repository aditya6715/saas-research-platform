# ── Stage 1: Python deps ──────────────────────────────────────────────────
FROM python:3.11-slim AS deps

WORKDIR /app

# Minimal system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps — use core requirements for fast, conflict-free build
COPY requirements-core.txt .
RUN pip install --no-cache-dir -r requirements-core.txt

# Optional: install full requirements (browser automation) for production use
# RUN pip install firecrawl-py browser-use playwright && playwright install chromium

# ── Stage 2: Application ──────────────────────────────────────────────────
FROM deps AS production

WORKDIR /app

COPY . .

# Runtime directories
RUN mkdir -p data/cache data/exports data/evidence reports logs

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Playwright browsers installed at runtime, not build time
# Run: playwright install chromium  (inside the container, first run)
ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
