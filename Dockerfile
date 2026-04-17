# ============================================================
# Production Dockerfile — Multi-stage, < 500 MB, non-root
# ============================================================

# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt


# Stage 2: Runtime
FROM python:3.11-slim AS runtime

# Non-root user
RUN groupadd -r agent && useradd -r -g agent -d /app agent

WORKDIR /app

# Copy virtualenv từ builder
COPY --from=builder /venv /venv

# Copy application
COPY app/ ./app/
COPY utils/ ./utils/
COPY entrypoint.sh ./entrypoint.sh

RUN chown -R agent:agent /app && chmod +x /app/entrypoint.sh

USER agent

ENV PATH=/venv/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1

CMD ["/app/entrypoint.sh"]
