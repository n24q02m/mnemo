"""Cover the ``__main__.py`` entrypoint guard line."""

from __future__ import annotations

import runpy
from unittest.mock import patch


def test_main_module_calls_server_main():
    """``python -m mnemo_mcp`` must dispatch to ``server.main``."""
    with patch("mnemo_mcp.server.main") as mock_main:
        runpy.run_module("mnemo_mcp", run_name="__main__")
        mock_main.assert_called_once()
