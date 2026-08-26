"""Shared fixtures for enterprise tests.

Re-exports the exact D1 doubles from tests/test_db_cf.py (FakeD1Worker over a
real SQLite database carrying migrations 0001-0003) so tests in this package
resolve them by their registered names without redefining the fakes.
"""

from test_db_cf import (
    d1_conn,  # noqa: F401
    fake_worker,  # noqa: F401
)
