# ==============================================================================
# PACTA ESCROW PROTOCOL — PRODUCTION CONTAINER (SOVEREIGN 2026.1)
# Multi-stage, minimal, non-root execution with healthcheck.
# ==============================================================================

FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY pacta ./pacta
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[dev]"

FROM python:3.12-slim AS runner

WORKDIR /app

# Security: Create non-privileged system user
RUN groupadd -r pacta && useradd -r -g pacta -d /app -s /sbin/nologin pacta

# Install runtime dependencies & curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source code
COPY . .

# Set permissions
RUN chown -R pacta:pacta /app

USER pacta

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8090/healthz || exit 1

# Launch production ASGI server
CMD ["uvicorn", "pacta.api:app", "--host", "0.0.0.0", "--port", "8090"]
