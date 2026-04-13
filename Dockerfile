# syntax=docker/dockerfile:1
# Multi-stage build for mnemo-mcp
# Python 3.13 + sqlite-vec
# All-in-one: persistent memory with Google Drive sync

# ========================
# Stage 1: Builder
# ========================
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=1

WORKDIR /app

# Install dependencies first (cached when deps don't change)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev

# Copy application code and install the project
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# ========================
# Stage 2: Runtime
# ========================
FROM python:3.13-slim-bookworm@sha256:061b6e52a07ab675f0e4a9428c5a8ee6bed996983427f4691f6bebf29c56d9dc

LABEL org.opencontainers.image.source="https://github.com/n24q02m/mnemo-mcp"
LABEL io.modelcontextprotocol.server.name="io.github.n24q02m/mnemo-mcp"

WORKDIR /app

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
