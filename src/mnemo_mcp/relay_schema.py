"""Config schema for relay page setup."""

from __future__ import annotations

from typing import Any

RELAY_SCHEMA: dict[str, Any] = {
    "server": "mnemo-mcp",
    "displayName": "Mnemo MCP",
    "description": (
        "Enter API keys for cloud capabilities. Leave all empty for pure "
        "local mode (ONNX models). Configure S3 + passphrase for "
        "encrypted multi-machine passport sync (Phase 2)."
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
        # Phase 2: passport sync S3 backend (optional)
        {
            "key": "SYNC_S3_BUCKET",
            "label": "S3 Bucket (passport sync)",
            "type": "text",
            "placeholder": "my-mnemo-bucket",
            "helpText": (
                "Optional. Bucket name for encrypted memory passport "
                "sync. Works with AWS S3, Cloudflare R2, Backblaze B2, "
                "MinIO, etc."
            ),
            "required": False,
        },
        {
            "key": "SYNC_S3_REGION",
            "label": "S3 Region",
            "type": "text",
            "placeholder": "us-east-1",
            "helpText": "Bucket region. Use 'auto' for Cloudflare R2.",
            "required": False,
        },
        {
            "key": "SYNC_S3_ENDPOINT",
            "label": "S3 Endpoint URL",
            "type": "text",
            "placeholder": "https://<acct>.r2.cloudflarestorage.com",
            "helpText": (
                "Custom endpoint for non-AWS S3 (R2 / B2 / MinIO). "
                "Leave blank for AWS S3."
            ),
            "required": False,
        },
        {
            "key": "SYNC_S3_ACCESS_KEY_ID",
            "label": "S3 Access Key ID",
            "type": "password",
            "placeholder": "AKIA...",
            "helpText": "S3-compatible access key.",
            "required": False,
        },
        {
            "key": "SYNC_S3_SECRET_ACCESS_KEY",
            "label": "S3 Secret Access Key",
            "type": "password",
            "placeholder": "...",
            "helpText": "S3-compatible secret key.",
            "required": False,
        },
        # Phase 2: passport bundle encryption passphrase
        {
            "key": "SYNC_PASSPHRASE",
            "label": "Passport Encryption Passphrase",
            "type": "password",
            "placeholder": "long random phrase",
            "helpText": (
                "Required if you enable S3 / GDrive passport sync. "
                "Used to derive an AES-256-GCM key via Argon2id. "
                "Only the Argon2id-derived hash is stored in config.enc; "
                "the raw passphrase NEVER lands on disk. WARNING: lost "
                "passphrase = unrecoverable bundles (no backdoor)."
            ),
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
            "priority": "Gemini > OpenAI",
            "description": "Used for memory importance scoring and graph analysis. Without a key, basic heuristics are used.",
        },
        {
            "label": "Passport Sync (Phase 2)",
            "priority": "S3 (R2 / B2 / MinIO) and / or Google Drive",
            "description": (
                "Encrypted memory passport bundles (AES-256-GCM + "
                "Argon2id KDF). Multi-backend mirror supported. "
                "Passphrase required."
            ),
        },
    ],
}
