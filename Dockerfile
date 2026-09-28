# syntax=docker/dockerfile:1
# Multi-stage build for mnemo-mcp: the HTTP MCP endpoint (de-hosted —
# there is no stdio spawn mode). Python 3.13 + sqlite-vec.
# Build:  docker build -t <repo>:http .
# Bind host/port and auth come from ~/.mnemo/config.toml ([server];
# port defaults to 8000), overridable via MNEMO_HOST / MNEMO_PORT.

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
# re-resolution — this is what pins hull-core and every other dependency
# to the audited revisions. The lockfile is regenerated with
# UV_NO_SOURCES=1 on commit so every requirement points at the public
# PyPI registry. Sources are a resolve-time concept and are not
# consulted under --frozen, so the build never needs a dev source tree
# that does not exist in the build context.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy application code and install the project
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ========================
# Stage 2: Runtime (HTTP MCP endpoint; single target)
# ========================
FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS http

LABEL org.opencontainers.image.source="https://github.com/n24q02m/mnemo-mcp"
LABEL io.modelcontextprotocol.server.name="io.github.n24q02m/mnemo-mcp"

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Set environment variables.
# Persistence contract: every data path in the server (mnemo_config_dir,
# db_path_for_namespace, hull instance settings) resolves under
# Path.home()/.mnemo -- no env var relocates them -- so HOME must point at
# the volume for memories.db, mode-3 subs/ and config.toml to persist in
# /data instead of vanishing with the container layer.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    HOME=/data

# Create non-root user and set permissions; pre-create the on-volume
# instance dir so the app never writes into a volume root it does not own.
RUN groupadd -r appuser && useradd -r -g appuser -d /home/appuser -m appuser \
    && mkdir -p /data/.mnemo \
    && chown -R appuser:appuser /app /data /home/appuser

VOLUME /data
USER appuser

# Default [server] port from ~/.mnemo/config.toml (hull settings default
# 8000); override via config or MNEMO_PORT.
EXPOSE 8000
ENTRYPOINT ["python", "-m", "mnemo_mcp"]
