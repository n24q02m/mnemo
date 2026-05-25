"""Config schema for relay page setup.

Relay form scope is **API keys only**. Sync backend selection is a
deployment-mode decision (env-driven, not user-input):

- **Local-relay / uvx (Method 1)**: no SYNC_S3_* env vars set →
  GDrive Device Code OAuth via existing flow (user authorises Google
  account, token stored in ~/.mnemo-mcp/tokens/).
- **HTTP deploy / docker (Method 2/3)**: operator sets SYNC_S3_BUCKET +
  SYNC_S3_ACCESS_KEY_ID + SYNC_S3_SECRET_ACCESS_KEY (+ optional REGION
  / ENDPOINT) + SYNC_PASSPHRASE via docker env → server detects S3
  mode at startup, **disables GDrive flow entirely**, sends encrypted
  bundles to S3-compatible storage.

The two backends are mutually exclusive at deployment level. See
docs/passport.md for the full operator runbook.
"""

from __future__ import annotations

from typing import Any

RELAY_SCHEMA: dict[str, Any] = {
    "server": "mnemo-mcp",
    "displayName": "Mnemo MCP",
    "description": (
        "Enter API keys for cloud capabilities. Leave all empty for pure "
        "local mode (ONNX models). Multi-machine passport sync is a "
        "deployment-mode setting (operator env vars, not configured here)."
    ),
    "fields": [
        {
            "key": "JINA_AI_API_KEY",
            "label": "Jina AI API Key",
            "type": "password",
            "placeholder": "jina_...",
            "helpUrl": "https://jina.ai/api-key",
            "helpText": "Embedding + Reranking (highest priority for both).",
            "required": False,
        },
        {
            "key": "GEMINI_API_KEY",
            "label": "Gemini API Key",
            "type": "password",
            "placeholder": "AIza...",
            "helpUrl": "https://aistudio.google.com/apikey",
            "helpText": "Embedding + LLM. Free tier available.",
            "required": False,
        },
        {
            "key": "OPENAI_API_KEY",
            "label": "OpenAI API Key",
            "type": "password",
            "placeholder": "sk-...",
            "helpUrl": "https://platform.openai.com/api-keys",
            "helpText": "Embedding + LLM (lower priority than Gemini).",
            "required": False,
        },
        {
            "key": "COHERE_API_KEY",
            "label": "Cohere API Key",
            "type": "password",
            "placeholder": "co-...",
            "helpUrl": "https://dashboard.cohere.com/api-keys",
            "helpText": "Embedding + Reranking.",
            "required": False,
        },
        {
            "key": "ANTHROPIC_API_KEY",
            "label": "Anthropic API Key",
            "type": "password",
            "placeholder": "sk-ant-...",
            "helpUrl": "https://console.anthropic.com/settings/keys",
            "helpText": "LLM (lower priority than OpenAI).",
            "required": False,
        },
        {
            "key": "XAI_API_KEY",
            "label": "xAI API Key",
            "type": "password",
            "placeholder": "xai-...",
            "helpUrl": "https://console.x.ai/",
            "helpText": "LLM (lower priority than Anthropic).",
            "required": False,
        },
    ],
    "capabilityInfo": [
        {
            "label": "Embedding",
            "priority": "Jina > Gemini > OpenAI > Cohere > Local ONNX",
            "description": "Vector embeddings for semantic memory search. Local mode uses Qwen3-Embedding (0.6B ONNX).",
        },
        {
            "label": "Reranking",
            "priority": "Jina > Cohere > Local ONNX",
            "description": "Re-ranks search results for accuracy. Local mode uses Qwen3-Reranker (0.6B ONNX).",
        },
        {
            "label": "LLM",
            "priority": "Gemini > OpenAI > Anthropic > xAI",
            "description": "Used for memory importance scoring and graph analysis. Without a key, basic heuristics are used.",
        },
        {
            "label": "Passport Sync (operator-config)",
            "priority": "S3 (env) XOR Google Drive (default)",
            "description": (
                "Mutually exclusive: deployment sets SYNC_S3_BUCKET + "
                "SYNC_PASSPHRASE env at docker spawn → S3 mode with "
                "encrypted bundles (AES-256-GCM + Argon2id). No S3 env "
                "→ Google Drive Device Code OAuth via this relay. See "
                "docs/passport.md for operator runbook."
            ),
        },
    ],
}
