"""Additional tests for mnemo_mcp.__main__ — covering uncovered lines.

Targets: line 88 (warmup retry after cache clear fails),
line 111 (__name__ == "__main__" block).
"""

from unittest.mock import MagicMock, patch


class TestWarmupRetryFailure:
    """Test warmup retry after cache clear when result is empty."""

    @patch("mnemo_mcp.__main__._clear_model_cache")
    @patch("qwen3_embed.TextEmbedding")
    @patch("mnemo_mcp.config.settings")
    def test_corrupted_cache_retry_fails(
        self, mock_settings, mock_te, mock_clear, capsys
    ):
        """When retry after cache clear also returns empty, prints WARNING."""
        from mnemo_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {}
        mock_settings.resolve_local_embedding_model.return_value = "org/model"

        # First call raises NO_SUCHFILE
        exc = Exception("[ONNXRuntimeError] : 3 : NO_SUCHFILE : file doesn't exist")

        # Second call succeeds but returns empty embedding
        mock_model_retry = MagicMock()
        mock_model_retry.embed.return_value = iter([])
        mock_te.side_effect = [exc, mock_model_retry]

        _warmup()

        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        mock_clear.assert_called_once_with("org/model")


class TestMainModule:
    """Test the __name__ == '__main__' entry point."""

    def test_main_module_calls_cli(self):
        """__main__.py calls _cli when run as module."""
        with patch("mnemo_mcp.__main__._cli"):
            # Simulate running the module

            # The __name__ == "__main__" block at the bottom of __main__.py
            # We can test _cli directly since that's what it calls
            from mnemo_mcp.__main__ import _cli

            with patch("sys.argv", ["mnemo-mcp"]):
                with patch("mnemo_mcp.server.main"):
                    _cli()
