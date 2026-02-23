"""Mnemo MCP Server entry point."""

import sys


def _warmup() -> None:
    """Pre-download models and validate setup to avoid first-run delays.

    Run this before adding mnemo-mcp to your MCP config:
        uvx mnemo-mcp warmup

    This downloads the local embedding model (~570 MB) so the first real
    connection does not timeout while downloading.
    """
    print("Mnemo MCP warmup: pre-downloading embedding model...")

    from mnemo_mcp.config import settings

    # 1. Check API keys first -- if valid cloud keys exist, skip local download
    keys = settings.setup_api_keys()
    if keys:
        print(f"  API keys found: {', '.join(keys.keys())}")
        print("  Validating cloud embedding models...")

        from mnemo_mcp.embedder import init_backend
        from mnemo_mcp.server import _EMBEDDING_CANDIDATES

        model = settings.resolve_embedding_model()
        candidates = [model] if model else _EMBEDDING_CANDIDATES

        for candidate in candidates:
            try:
                backend = init_backend("litellm", candidate)
                dims = backend.check_available()
                if dims > 0:
                    print(f"  Cloud embedding ready: {candidate} (dims={dims})")
                    print("Warmup complete! Cloud embedding will be used.")
                    return
            except Exception:
                continue

        print("  Cloud embedding not available, falling back to local model...")

    # 2. Download local embedding model
    local_model = settings.resolve_local_embedding_model()
    print(f"  Downloading local model: {local_model} (~570 MB)...")
    print("  This may take a few minutes on first run.")

    from qwen3_embed import TextEmbedding

    model = TextEmbedding(model_name=local_model)
    result = list(model.embed(["warmup test"]))
    if result:
        print(f"  Local embedding ready (dims={len(result[0])})")
    else:
        print("  WARNING: Local embedding test failed")

    print("Warmup complete!")


def _cli() -> None:
    """CLI dispatcher: server (default), warmup, or setup-sync subcommand."""
    if len(sys.argv) >= 2 and sys.argv[1] == "warmup":
        _warmup()
    elif len(sys.argv) >= 2 and sys.argv[1] == "setup-sync":
        from mnemo_mcp.sync import setup_sync

        remote_type = sys.argv[2] if len(sys.argv) >= 3 else "drive"
        setup_sync(remote_type)
    else:
        from mnemo_mcp.server import main

        main()


if __name__ == "__main__":
    _cli()
