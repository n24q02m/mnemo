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

# Install dependencies first (cached when deps don't change).
# --frozen: install from the committed uv.lock exactly as-is, skipping
# re-resolution. The lockfile is regenerated with UV_NO_SOURCES=1 on
# commit so n24q02m-mcp-core already points at the PyPI registry, not
# the dev-only ../mcp-core path from [tool.uv.sources]. Sources are a
# resolve-time concept and are not consulted under --frozen, so the
# Docker build picks the PyPI wheel without seeing the sibling path
# that does not exist in the build context.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy application code and install the project
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ========================
# Stage 2: Runtime base (shared by stdio + http targets)
# ========================
# Multi-target Dockerfile per spec
# `~/projects/.superpower/mcp-core/specs/2026-04-30-multi-mode-stdio-http-architecture.md`
# section D6. Build stdio: `docker buildx build --target stdio -t <repo>:stdio .`
# Build http:  `docker buildx build --target http  -t <repo>:http .`
# Build latest (= http): `docker buildx build --target http -t <repo>:latest .`
FROM python:3.13-slim-bookworm@sha256:386df64585134ba00b1d5e307acb1e72f33e9e87dbbb00aad9b8f24dbb51db72 AS runtime

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

# ========================
# Stage 3a: stdio target (default for plugin marketplace & uvx-style usage)
# ========================
FROM runtime AS stdio
ENV MCP_TRANSPORT=stdio
ENTRYPOINT ["python", "-m", "mnemo_mcp"]

# ========================
# Stage 3b: http target (multi-user remote daemon)
# ========================
FROM runtime AS http
ENV MCP_TRANSPORT=http \
    MCP_PORT=8080
EXPOSE 8080
ENTRYPOINT ["python", "-m", "mnemo_mcp"]
