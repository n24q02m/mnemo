from __future__ import annotations

import os
import subprocess
import sys


def test_server_import_emits_no_runtime_warnings() -> None:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("MNEMO_", "GOOGLE_"))
    }
    result = subprocess.run(
        [sys.executable, "-Werror", "-c", "import mnemo_mcp.server"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
