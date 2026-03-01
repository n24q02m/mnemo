import importlib.metadata
import sys
from unittest.mock import MagicMock, patch

import pytest


def mock_version(name):
    if name == "mnemo-mcp":
        return "0.0.0-test"
    raise importlib.metadata.PackageNotFoundError(name)


patcher = patch("importlib.metadata.version", side_effect=mock_version)
patcher.start()


@pytest.fixture
def mock_dependencies():
    mock_db = MagicMock()
    mock_embedder = MagicMock()
    mock_fast_mcp = MagicMock()

    def identity_decorator(*args, **kwargs):
        def wrapper(func):
            return func

        return wrapper

    mock_fast_mcp.tool.side_effect = identity_decorator
    mock_fast_mcp.resource.side_effect = identity_decorator
    mock_fast_mcp.prompt.side_effect = identity_decorator
    mock_mcp_module = MagicMock()
    mock_mcp_module.FastMCP.return_value = mock_fast_mcp
    modules_to_patch = {
        "mnemo_mcp.db": mock_db,
        "mnemo_mcp.embedder": mock_embedder,
        "mcp.server.fastmcp": mock_mcp_module,
    }
    with patch.dict(sys.modules, modules_to_patch):
        if "mnemo_mcp.server" in sys.modules:
            del sys.modules["mnemo_mcp.server"]
        yield
        if "mnemo_mcp.server" in sys.modules:
            del sys.modules["mnemo_mcp.server"]


@pytest.mark.asyncio
async def test_log_level_invalid_rejection(mock_dependencies):
    from mnemo_mcp import server

    with patch.object(server, "logger") as mock_logger:
        with patch.object(server, "settings") as mock_settings:
            mock_settings.log_level = "INFO"
            with patch.object(
                server, "_get_ctx", return_value=(MagicMock(), MagicMock(), MagicMock())
            ):
                result = await server.config(
                    action="set", key="log_level", value="INVALID_LEVEL"
                )
                assert '"error":' in result
                assert "Invalid log level" in result
                mock_logger.remove.assert_not_called()
                mock_logger.add.assert_not_called()


@pytest.mark.asyncio
async def test_log_level_valid_update(mock_dependencies):
    from mnemo_mcp import server

    with patch.object(server, "logger") as mock_logger:
        with patch.object(server, "settings") as mock_settings:
            mock_settings.log_level = "INFO"
            with patch.object(
                server, "_get_ctx", return_value=(MagicMock(), MagicMock(), MagicMock())
            ):
                result = await server.config(
                    action="set", key="log_level", value="DEBUG"
                )
                assert '"status": "updated"' in result
                mock_logger.remove.assert_called_once()
                mock_logger.add.assert_called_once()
