# syntax=docker/dockerfile:1
# Multi-stage build for mnemo-mcp
# Python 3.13 + sqlite-vec + rclone
# All-in-one: persistent memory with embedded sync

# ========================
# Stage 1: Builder
# ========================
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install dependencies first (cached when deps don't change)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Copy application code and install the project
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ========================
# Stage 2: Runtime
# ========================
FROM python:3.13-slim-bookworm

WORKDIR /app

# Install rclone for sync support
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    && curl -fsSL https://rclone.org/install.sh | bash \
    && apt-get purge -y curl unzip \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    DB_PATH=/data/memories.db

# Create non-root user and set permissions
RUN groupadd -r appuser && useradd -r -g appuser -d /home/appuser -m appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data /home/appuser

VOLUME /data
USER appuser

# Stdio transport by default
CMD ["python", "-m", "mnemo_mcp"]
