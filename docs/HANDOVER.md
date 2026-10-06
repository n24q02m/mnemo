# mnemo Handover

Operational handover for [mnemo](https://github.com/n24q02m/mnemo) — MCP
server for persistent AI memory. Current stable line: **mnemo-mcp 2.20.x**.

## Current operation

- PyPI dist: `mnemo-mcp`. Console scripts: `mnemo-mcp` (server + config/token
  subcommands; legacy command alias) and `mnemo` / `mnemo-pilot` (CLI
  consumer that talks straight to the memory DB — no server needed).
- **Streamable HTTP only.** The stdio transport was removed post-de-host; the
  server runs one HTTP MCP endpoint (`/mcp`). Note: the immutable MCP registry
  metadata for 2.20.0 still declares stdio — the README/runtime is canonical
  (HTTP-only).
- Post-de-host the project operates no hosted MCP endpoint; remote access is a
  self-hosted instance on a host you own, fronted by your own TLS proxy (the
  server binds plain HTTP). Public OCI image publication is discontinued —
  build containers from source (`docker build --target http`) or use
  `docker-compose.http.yml`.
- Local state is machine-bound under `~/.mnemo/` (TC-Local): `config.toml`,
  `memories.db`, per-namespace `subs/<ns>/memories.db`.

## Install

```bash
# Run the HTTP server (uvx)
uvx --from mnemo-mcp mnemo-mcp     # serves http://127.0.0.1:8000/mcp by default
claude mcp add --transport http mnemo http://127.0.0.1:8000/mcp

# CLI consumer without a server
uvx --from mnemo-mcp mnemo recall --db ./mem.db "package naming" --k 3

# Claude Code plugin (needs a running instance)
/plugin marketplace add n24q02m/claude-plugins
/plugin install mnemo-mcp@n24q02m-plugins
```

Any MCP client: point it at the `/mcp` endpoint of a running instance
(Streamable HTTP). Codex / Gemini CLI / Cursor / Windsurf: register the
`http://<host>:<port>/mcp` endpoint in the client's MCP settings.

## Run

```bash
# Dev: no-auth, loopback only
uv run mnemo-mcp                    # binds 127.0.0.1:8000, auth = "no-auth" by default
uv run mnemo-mcp config-init        # writes ~/.mnemo/config.toml from the template

# Always-on: docker compose (token auth, loopback-published port)
cp mnemo-config/config.example.toml mnemo-config/config.toml   # edit auth + token_hash
docker compose -f docker-compose.http.yml up --build -d
# MCP endpoint: http://127.0.0.1:8771/mcp   (override host port: MNEMO_PORT=9000)
```

`no-auth` refuses non-loopback binds — localhost-only by construction.

### Token setup

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # 1. mint token
MNEMO_AUTH_TOKEN=<token> uv run mnemo-mcp token-hash            # 2. print scrypt$ hash
# 3. paste the hash into token_hash in mnemo-config/config.toml; give clients the token
```

`mnemo-mcp token-verify <token> <scrypt$...>` verifies a candidate against a
stored hash. Clients send the token as a Bearer credential
(`--header "Authorization: Bearer <token>"`).

## Auth modes (`[server] auth`)

| Mode | Bind | Storage | Who can read data |
|---|---|---|---|
| `no-auth` (default) | loopback only (non-loopback bind refused) | `~/.mnemo/memories.db` | Only your OS user |
| `token` | any | same, one shared `default` namespace | Anyone holding the shared token |
| `multi` | any | per-namespace `~/.mnemo/subs/<ns>/memories.db` via `users.toml` | Each token holder sees only their namespace |

## Build, run, and verify

```bash
git clone https://github.com/n24q02m/mnemo.git && cd mnemo
uv sync
uv run mnemo-mcp        # dev HTTP server
uv run pytest           # dev group: pytest, pytest-asyncio, pytest-timeout, ruff, ty
```

## Model configuration policy

- Task cells in `config.toml` (`[models.embed]`, `rerank`, `chat`,
  `jev_score`) are independent: `base_url + api_key + model`, OpenAI-spec
  HTTP; mix local and cloud freely. Keys are host-only and may come from the
  `HULL_<TASK>_API_KEY` env vars instead of the file.
- **No sanctioned default cloud model.** An unconfigured cell disables its
  feature — e.g. LLM compression (`[models.chat]`) gracefully skips per-turn
  compression when unconfigured, targeting ~3x token reduction at >=0.9 fact
  retention when configured. Empty embedding/rerank chains select local
  Fastretrieval ONNX/GGUF models; configured cloud chains never silently fall
  back to local.
- Per-task chain selection: `EMBEDDING_MODELS` / `RERANK_MODELS` /
  `LLM_MODELS` (CSV `provider/model`, order = litellm fallback; provider
  inferred from the prefix; keys never select a model).

## Data and safety invariants

- Provider keys are host-only config (`config.toml` / `HULL_<TASK>_API_KEY`),
  never visible to MCP clients.
- Every storage artifact lives under `~/.mnemo/` owned by your OS user.
- `multi` mode isolates namespaces at the DB-file level; a namespace holder
  cannot see another namespace's memories.

## In-flight and rollback

Roll back a source change by reverting the owning commit; SQLite memory DBs
are forward-compatible instance state — do not delete them as a rollback
shortcut. Docker state persists in the `mnemo-data` volume; config edits take
effect on restart. Port gotcha: `8000` is the bare `uvx`/`uv run` default,
`8771` is the compose default (`MNEMO_PORT` overrides the compose host port).
