# ── Stage 1: Python deps ──────────────────────────────────────────────────
FROM python:3.11-slim AS deps

WORKDIR /app

# System deps for Playwright chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget ca-certificates \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (no dev/test deps in production image)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright chromium browser
RUN playwright install chromium --with-deps 2>/dev/null || true

# ── Stage 2: Application ──────────────────────────────────────────────────
FROM deps AS production

WORKDIR /app

COPY . .

# Create runtime directories
RUN mkdir -p data/cache data/exports data/evidence reports logs

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
