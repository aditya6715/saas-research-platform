# ── Stage 1: dependency installer ────────────────────────────────────────
FROM python:3.11-slim AS deps

WORKDIR /app

# Install system deps needed by Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget gnupg ca-certificates \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser (chromium only to minimise image size)
RUN playwright install chromium --with-deps

# ── Stage 2: production image ─────────────────────────────────────────────
FROM deps AS production

WORKDIR /app

# Copy project files
COPY . .

# Create runtime directories
RUN mkdir -p data/cache data/exports data/evidence reports logs

# Default env (all secrets must be passed at runtime via --env-file or -e)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python", "main.py"]
CMD ["run", "--input", "data/apps.csv"]
