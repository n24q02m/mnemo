"""Alembic environment for mnemo-mcp.

This environment is tuned for SQLite + WAL and raw-SQL migrations
(``op.execute(...)`` style). We do not use SQLAlchemy ORM models, so
``target_metadata`` is set to ``None`` and ``autogenerate`` is not used.

The database URL is resolved at runtime from the ``MNEMO_DB_PATH`` environment
variable (or the ``-x db_path=...`` CLI override) so the same migration scripts
work for the production DB and for tests using temporary paths.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, event, pool

from alembic import context

# Alembic Config object — values from alembic.ini
config = context.config

# Initialise Python logging only when an ini file is provided. Tests may invoke
# the migration runner programmatically without a config file path.
if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        # Logging config is best-effort; never fail a migration on logger setup.
        pass

# We use raw-SQL migrations, not autogenerate.
target_metadata = None


def _resolve_db_url() -> str:
    """Resolve the SQLite URL from CLI override or env, with a sane default.

    Priority:
    1. ``-x db_path=/abs/path`` Alembic CLI override (highest, used by tests).
    2. ``MNEMO_DB_PATH`` environment variable.
    3. ``alembic.ini`` ``sqlalchemy.url`` value.
    4. Default ``~/.mnemo-mcp/memories.db``.
    """
    x_args = context.get_x_argument(as_dictionary=True)
    if "db_path" in x_args:
        path = Path(x_args["db_path"]).expanduser().resolve()
        return f"sqlite:///{path.as_posix()}"

    env_path = os.environ.get("MNEMO_DB_PATH")
    if env_path:
        path = Path(env_path).expanduser().resolve()
        return f"sqlite:///{path.as_posix()}"

    ini_url = config.get_main_option("sqlalchemy.url") or ""
    if ini_url and not ini_url.startswith("driver://"):
        return ini_url

    default_path = (Path.home() / ".mnemo-mcp" / "memories.db").resolve()
    return f"sqlite:///{default_path.as_posix()}"


def run_migrations_offline() -> None:
    """Emit migration SQL to stdout instead of running against a DB."""
    url = _resolve_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live SQLite database."""
    url = _resolve_db_url()
    engine = create_engine(
        url,
        poolclass=pool.NullPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.execute("PRAGMA busy_timeout = 5000")
            cursor.execute("PRAGMA foreign_keys = ON")
        finally:
            cursor.close()

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER limitations need batch mode
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
