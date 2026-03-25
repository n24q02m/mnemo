"""Config schema for relay page setup."""

from mcp_relay_core.schema.types import RelayConfigSchema

RELAY_SCHEMA: RelayConfigSchema = {
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
}
