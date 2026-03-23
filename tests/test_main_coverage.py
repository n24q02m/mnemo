"""Additional tests for mnemo_mcp.__main__ -- pure server entry coverage."""

import importlib
from unittest.mock import patch


class TestMainModuleEntryPoint:
    """Test the __name__ == '__main__' entry point is a pure server start."""

    def test_main_is_server_main(self):
        """__main__.main is server.main."""
        import mnemo_mcp.__main__ as main_mod

        # Reload to ensure clean state (no mocks from other tests)
        importlib.reload(main_mod)
        from mnemo_mcp.server import main as server_main

        assert main_mod.main is server_main

    def test_main_module_runs(self):
        """Calling main from __main__ runs server."""
        with patch("mnemo_mcp.server.main") as mock_main:
            # Need to reload since main is imported at module level
            import mnemo_mcp.__main__ as main_mod

            importlib.reload(main_mod)
            main_mod.main()
            mock_main.assert_called_once()
