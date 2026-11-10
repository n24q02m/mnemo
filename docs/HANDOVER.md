# mnemo Handover

Operational handover for [mnemo](https://github.com/n24q02m/mnemo) — MCP
server for persistent AI memory. Current stable line: **n24q02m-mnemo 2.21.x**.

## Current operation

- PyPI dist: `n24q02m-mnemo` (renamed from `mnemo-mcp`). Console scripts:
  `n24q02m-mnemo` (server + config/token subcommands; `mnemo-mcp` is the
  legacy alias of the same entry point) and `mnemo` / `mnemo-pilot` (CLI
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
uvx n24q02m-mnemo                 # serves http://127.0.0.1:8000/mcp by default
claude mcp add --transport http mnemo http://127.0.0.1:8000/mcp

# CLI consumer without a server
uvx --from n24q02m-mnemo mnemo recall --db ./mem.db "package naming" --k 3

# Claude Code plugin (needs a running instance)
/plugin marketplace add n24q02m/claude-plugins
/plugin install mnemo@n24q02m-plugins
```

Any MCP client: point it at the `/mcp` endpoint of a running instance
(Streamable HTTP). Codex / Gemini CLI / Cursor / Windsurf: register the
`http://<host>:<port>/mcp` endpoint in the client's MCP settings.

## Run

```bash
# Dev: no-auth, loopback only
uv run n24q02m-mnemo                    # binds 127.0.0.1:8000, auth = "no-auth" by default
uv run n24q02m-mnemo config-init        # writes ~/.mnemo/config.toml from the template

# Always-on: docker compose (token auth, loopback-published port)
cp mnemo-config/config.example.toml mnemo-config/config.toml   # edit auth + token_hash
docker compose -f docker-compose.http.yml up --build -d
# MCP endpoint: http://127.0.0.1:8771/mcp   (override host port: MNEMO_PORT=9000)
```

`no-auth` refuses non-loopback binds — localhost-only by construction.

### Token setup

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # 1. mint token
MNEMO_AUTH_TOKEN=<token> uv run n24q02m-mnemo token-hash            # 2. print scrypt$ hash
# 3. paste the hash into token_hash in mnemo-config/config.toml; give clients the token
```

`n24q02m-mnemo token-verify <token> <scrypt$...>` verifies a candidate against a
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
uv run n24q02m-mnemo        # dev HTTP server
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

### Provider credential pools (hull 0.5)

One key per cell took a whole feature down on a 401/429. Cells now seed an
ordered **pool** per provider identity, implemented in hull
(`hull_core.credentials`: `CredentialStore`, `KeyPool`, `AccountRegistry`) and
adopted by every mnemo provider call site (`mnemo/keys.py`):

- Store: `~/.mnemo/credentials.db` (SQLite WAL, tables
  `provider_credentials` / `provider_accounts`), keys AES-256-GCM sealed with
  `~/.mnemo/.credential-key` (created once, `0600`). Instance-scoped on
  purpose: the machine-wide `~/.hull/hull.db` belongs to other hull products.
- Call path: lease the highest-priority usable credential → build the hull
  `OpenAICompatClient` from that credential (`api_key` + `base_url`; the *cell*
  keeps the model id, because four task cells share one provider pool) → call
  → `record_success` / `record_failure(status)`.
- Policy (hull's, not re-implemented here): 401/403 disable; 429 cooldown from
  `Retry-After`/`rate_limit_reset` clamped 1 s…1 h (default 60 s); 5xx retry
  once then rotate; any other status re-raises with the credential untouched;
  bounded attempts `total × (1 + max_5xx_retries)`; exhaustion raises
  `PoolExhaustedError`, remapped by mnemo to
  `mnemo.exceptions.ProviderCredentialsExhausted` (counts + `retry_after` +
  key-redacted last error).
- Seeding: on server start (`lifespan`) and lazily on first use, a cell's
  legacy key is migrated into its pool **only while the pool is empty**
  (`ensure_seeded`, idempotent). The env var is never deleted; an
  operator-removed key is not resurrected. Config: optional `provider` /
  `account` keys in `[models.<task>]`; the default pool is the unaccounted one
  and an unknown account is reported instead of silently creating one.
- Concurrency: hull leases a credential for one in-flight attempt, so pooled
  calls are gated to the pool size per event loop. Under one key that means
  provider calls serialize; with N keys, N may run at once and rotation never
  hands the same key to two attempts.
- Operator surface: hull 0.5 ships the pool as a **library** (no credential
  CLI yet), so keys and accounts are managed through
  `hull_core.credentials` against `mnemo.keys.credential_store()`; the masked
  health view is `mnemo.keys.pool_health(cell)`. Disabled keys are re-enabled
  explicitly (`store.enable(id)`), never automatically.
- Residual: hull's `ProviderError` carries the status but not the response
  headers, so a real `429` cools down for hull's 60 s default; mnemo already
  forwards `retry_after` / `rate_limit_reset` / `headers` when an error
  carries them. The `Retry-After` hint needs a hull-side change (add response
  headers to `ProviderError`), not another mnemo workaround.


## Data and safety invariants

- Provider keys are host-only material (`config.toml` /
  `HULL_<TASK>_API_KEY`, or the sealed pool store
  `~/.mnemo/credentials.db`), never visible to MCP clients. No key reaches a
  log line, an error message, or a tool response: pool health is exposed only
  as a 4-character hint.
- Every storage artifact lives under `~/.mnemo/` owned by your OS user.
- `multi` mode isolates namespaces at the DB-file level; a namespace holder
  cannot see another namespace's memories.

## In-flight and rollback

Roll back a source change by reverting the owning commit; SQLite memory DBs
are forward-compatible instance state — do not delete them as a rollback
shortcut. Docker state persists in the `mnemo-data` volume; config edits take
effect on restart. Port gotcha: `8000` is the bare `uvx`/`uv run` default,
`8771` is the compose default (`MNEMO_PORT` overrides the compose host port).
