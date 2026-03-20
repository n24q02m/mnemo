"""Test missing ImportError coverage for _has_gguf_support."""

import sys
from unittest.mock import patch

from mnemo_mcp.config import _has_gguf_support


def test_gguf_support_import_error():
    import builtins

    orig_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "llama_cpp":
            raise ImportError("mocked")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        # We manually save and restore only the 'llama_cpp' entry
        # rather than using patch.dict(sys.modules) which can cause
        # side effects with other C extensions like numpy being
        # unexpectedly unloaded when the dict is restored.
        original_module = sys.modules.get("llama_cpp", None)
        if "llama_cpp" in sys.modules:
            del sys.modules["llama_cpp"]

        try:
            assert _has_gguf_support() is False
        finally:
            if original_module is not None:
                sys.modules["llama_cpp"] = original_module
