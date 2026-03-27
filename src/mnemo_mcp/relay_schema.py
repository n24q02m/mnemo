"""Config schema for relay page setup."""

from __future__ import annotations

from typing import Any

RELAY_SCHEMA: dict[str, Any] = {
    "server": "mnemo-mcp",
    "displayName": "Mnemo MCP",
    "modes": [
        {
            "id": "local",
            "label": "Local Mode",
            "description": "Default. Uses local ONNX embeddings + SQLite. No config needed.",
            "fields": [],
        },
        {
            "id": "cloud",
            "label": "Cloud Mode",
            "description": "Use cloud API keys for embeddings and reranking.",
            "fields": [
                {
                    "key": "JINA_AI_API_KEY",
                    "label": "Jina AI API Key",
                    "type": "password",
                    "placeholder": "jina_...",
                    "helpUrl": "https://jina.ai/api-key",
                    "helpText": "Highest priority. Embedding + reranking.",
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
                    "helpText": "Embedding only.",
                    "required": False,
                },
                {
                    "key": "COHERE_API_KEY",
                    "label": "Cohere API Key",
                    "type": "password",
                    "placeholder": "co-...",
                    "helpUrl": "https://dashboard.cohere.com/api-keys",
                    "helpText": "Embedding + reranking.",
                    "required": False,
                },
            ],
        },
    ],
    "sections": [
        {
            "id": "google_drive_sync",
            "label": "Google Drive Sync",
            "description": "Sync memory database across machines via Google Drive",
            "fields": [
                {
                    "key": "SYNC_ENABLED",
                    "label": "Enable Sync",
                    "type": "boolean",
                    "required": False,
                    "helpText": "Enable automatic Google Drive sync for memory database",
                },
                {
                    "key": "GOOGLE_DRIVE_CLIENT_ID",
                    "label": "OAuth Client ID",
                    "type": "text",
                    "placeholder": "123456789.apps.googleusercontent.com",
                    "required": False,
                    "helpText": "Create at console.cloud.google.com/apis/credentials (OAuth 2.0 Client ID, type: TV/Limited Input)",
                },
                {
                    "key": "SYNC_FOLDER",
                    "label": "Drive Folder",
                    "type": "text",
                    "placeholder": "mnemo-mcp",
                    "required": False,
                    "helpText": "Google Drive folder name for sync (default: mnemo-mcp)",
                },
            ],
        },
    ],
}
