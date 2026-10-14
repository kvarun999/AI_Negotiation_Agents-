# ============================================================
# AI Trade Negotiation — Dockerfile
# ============================================================
# Builds the FastAPI service image using a lightweight Python
# base.  All configuration is injected at runtime via
# environment variables defined in docker-compose.yml or a
# .env file.
# ============================================================

FROM python:3.11-slim

# ── Metadata ────────────────────────────────────────────────
LABEL maintainer="AI Negotiation Agent"
LABEL description="FastAPI service orchestrating two-country trade negotiation agents."

# ── System hygiene ──────────────────────────────────────────
# Do not write .pyc files and disable output buffering so
# container logs appear immediately.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ── Create a non-root application user ──────────────────────
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# ── Set working directory ───────────────────────────────────
WORKDIR /app

# ── Install Python dependencies ──────────────────────────────
# Copy requirements first to leverage Docker layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ── Copy application source ──────────────────────────────────
COPY agents/   ./agents/
COPY tests/    ./tests/
COPY main.py   .
COPY scoring.py .

# The ./data directory is NOT baked into the image — it is
# provided at runtime via the volume mount defined in
# docker-compose.yml.  This guarantees the trade_positions.json
# data can be updated without rebuilding the image.

# ── Permissions ──────────────────────────────────────────────
# Allow the non-root user to write the negotiation log and
# any pytest cache files inside /app.
RUN mkdir -p /app/logs \
 && chown -R appuser:appgroup /app
USER appuser

# ── Expose API port ──────────────────────────────────────────
EXPOSE 8000

# ── Health-check ─────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

# ── Entrypoint ───────────────────────────────────────────────
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
