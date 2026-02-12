# Multi-stage build for mnemo-mcp
# Python 3.13 + sqlite-vec + rclone
# All-in-one: persistent memory with embedded sync

FROM python:3.13-slim-bookworm AS builder

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# Install dependencies
RUN uv sync --frozen --no-dev

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

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app/src

# Default data directory
ENV DB_PATH=/data/memories.db
VOLUME /data

# Stdio transport by default
CMD ["python", "-m", "mnemo_mcp"]
