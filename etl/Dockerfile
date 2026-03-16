# ──────────────────────────────────────────────
# Stage 1: build dependencies
# ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ──────────────────────────────────────────────
# Stage 2: lean runtime image
# ──────────────────────────────────────────────
FROM python:3.12-slim

# Runtime libpq only
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# App files
WORKDIR /app
COPY main.py        .
COPY entrypoint.sh  .
RUN chmod +x /app/entrypoint.sh

# Non-root user for security
RUN useradd --create-home --shell /bin/sh pipeline
USER pipeline

ENTRYPOINT ["/app/entrypoint.sh"]
