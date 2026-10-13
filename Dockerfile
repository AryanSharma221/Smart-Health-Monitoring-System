# =============================================================================
# SMART HEALTH MONITORING SYSTEM — PRODUCTION DOCKERFILE
# Multi-stage / hardened non-root container for FastAPI ASGI backend
# =============================================================================

FROM python:3.12-slim-bookworm AS base

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system runtime dependencies (curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python application dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# Create an unprivileged non-root user and group
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /sbin/nologin -d /app appuser

# Copy application source code
COPY database/ /app/database/
COPY services/ /app/services/
COPY alembic.ini /app/alembic.ini

# Ensure non-root ownership
RUN chown -R appuser:appgroup /app

# Switch to unprivileged runtime user
USER appuser

# Expose standard application port
EXPOSE 8000

# Docker native liveness healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

# Production ASGI server entry point
CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
