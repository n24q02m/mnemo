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

_EMBEDDING_SUGGESTED = [
    "jina_ai/jina-embeddings-v5-text-small",
    "gemini/gemini-embedding-001",
    "openai/text-embedding-3-large",
    "cohere/embed-multilingual-v3.0",
]
_RERANK_SUGGESTED = ["jina_ai/jina-reranker-v3", "cohere/rerank-v3.5"]
_LLM_SUGGESTED = [
    "gemini/gemini-3-flash-preview",
    "openai/gpt-5.4-mini-2026-03-17",
    "anthropic/claude-haiku-4-5",
    "xai/grok-4-fast",
]


def _key_field(key: str, label: str, ph: str, url: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "type": "password",
        "placeholder": ph,
        "helpUrl": url,
        "derived": True,
        "required": False,
    }


RELAY_SCHEMA: dict[str, Any] = {
    "server": "mnemo-mcp",
    "displayName": "Mnemo MCP",
    "description": (
        "Pick models per task (order = fallback). Leave a task empty for "
        "local ONNX (embedding/rerank) — LLM features need at least one model. "
        "Key fields appear automatically for the providers your models use."
    ),
    "fields": [
        {
            "key": "EMBEDDING_MODELS",
            "label": "Embedding models",
            "type": "model-chain",
            "task": "embedding",
            "suggestedModels": _EMBEDDING_SUGGESTED,
            "hasLocal": True,
            "placeholder": "add embedding model…",
        },
        {
            "key": "RERANK_MODELS",
            "label": "Rerank models",
            "type": "model-chain",
            "task": "rerank",
            "suggestedModels": _RERANK_SUGGESTED,
            "hasLocal": True,
            "placeholder": "add rerank model…",
        },
        {
            "key": "LLM_MODELS",
            "label": "LLM models",
            "type": "model-chain",
            "task": "chat",
            "suggestedModels": _LLM_SUGGESTED,
            "hasLocal": False,
            "placeholder": "add LLM model…",
        },
        _key_field(
            "JINA_AI_API_KEY", "Jina AI API Key", "jina_...", "https://jina.ai/api-key"
        ),
        _key_field(
            "GEMINI_API_KEY",
            "Gemini API Key",
            "AIza...",
            "https://aistudio.google.com/apikey",
        ),
        _key_field(
            "OPENAI_API_KEY",
            "OpenAI API Key",
            "sk-...",
            "https://platform.openai.com/api-keys",
        ),
        _key_field(
            "COHERE_API_KEY",
            "Cohere API Key",
            "co-...",
            "https://dashboard.cohere.com/api-keys",
        ),
        _key_field(
            "ANTHROPIC_API_KEY",
            "Anthropic API Key",
            "sk-ant-...",
            "https://console.anthropic.com/settings/keys",
        ),
        _key_field("XAI_API_KEY", "xAI API Key", "xai-...", "https://console.x.ai/"),
    ],
    "capabilityInfo": [
        {
            "label": "Embedding",
            "priority": "configurable",
            "description": "Vector embeddings for semantic memory. Empty = local Qwen3-Embedding ONNX.",
        },
        {
            "label": "Reranking",
            "priority": "configurable",
            "description": "Re-ranks search results. Empty = local Qwen3-Reranker ONNX.",
        },
        {
            "label": "LLM",
            "priority": "configurable",
            "description": "Memory importance scoring + graph analysis. Empty = basic heuristics.",
        },
        {
            "label": "Passport Sync (operator-config)",
            "priority": "S3 (env) XOR Google Drive (default)",
            "description": (
                "Mutually exclusive: deployment sets SYNC_S3_BUCKET + "
                "SYNC_PASSPHRASE env at docker spawn -> S3 mode with "
                "encrypted bundles (AES-256-GCM + Argon2id). No S3 env "
                "-> Google Drive Device Code OAuth via this relay. See "
                "docs/passport.md for operator runbook."
            ),
        },
    ],
}
