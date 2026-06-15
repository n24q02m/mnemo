# Passport Sync

**Passport sync** is an end-to-end-encrypted memory backup / restore loop
that lets you carry your full memory history across machines without
exposing plaintext to the storage backend.

## Concept

A *passport* is a single self-contained encrypted bundle that snapshots
your memory store (manifest + memory rows + entity / edge sections + room
for embeddings). The bundle is opaque to whichever backend stores
it -- Cloudflare R2, AWS S3, Backblaze B2, MinIO, or Google Drive only ever
see ciphertext.

When you bootstrap a fresh machine you supply your passphrase, point at
your backend, and `config(action="import_passport")` rehydrates the local
SQLite store with the full passport content.

## Backend choice (XOR per deployment mode)

| Backend | Pros | Cons |
|---|---|---|
| **S3** (R2 / B2 / MinIO / AWS) | Cheap (CF R2 free tier covers most users), portable, no API rate limits, easy multi-region | Requires you to register a bucket + IAM key |
| **Google Drive** | Zero infra setup if you already have a Google account, OAuth Device Code flow | API quotas, slower for large bundles, ties you to Google |

**The two backends are mutually exclusive at deployment level (XOR).** The
2026-05-14 Test B design drops the legacy `SYNC_BACKEND="s3,gdrive"`
multi-mirror semantics: operator picks ONE backend per deployment.

Resolution rule (`sync.resolve_active_backend`):

- `SYNC_S3_BUCKET` is set (env var OR pydantic `settings.sync_s3_bucket`) →
  active backend = **S3**. GDrive Device Code OAuth is **disabled** at
  startup; the relay form does NOT prompt for a Google account.
- Otherwise → active backend = **GDrive**. The relay form drives the
  Device Code flow for the end-user's Google account.

Env var takes precedence over the pydantic field so an operator can
override a persisted bucket from `config.json` without rewriting it.

### Per-mode runbook

#### Method 1 (local-relay / uvx) → GDrive

End-user runs `uvx mnemo-mcp --http`, opens the relay URL, pastes API
keys, then authorises Google Drive via Device Code. No S3 env vars set.

```bash
# uvx (no S3 env vars; GDrive flow auto-fires after relay form submit)
uvx mnemo-mcp --http
```

#### Method 2/3 (HTTP deploy / docker) → S3

Operator sets S3 + passphrase env at container spawn. End-users only
paste API keys via the relay form — the passport sync is invisible to
them and S3-backed under the hood.

```bash
docker run \
  -e SYNC_S3_BUCKET=mnemo-prod-passport \
  -e SYNC_S3_ACCESS_KEY_ID=AKIA... \
  -e SYNC_S3_SECRET_ACCESS_KEY=... \
  -e SYNC_S3_REGION=auto \
  -e SYNC_S3_ENDPOINT=https://<account>.r2.cloudflarestorage.com \
  -e SYNC_PASSPHRASE='<strong-shared-passphrase>' \
  -e PUBLIC_URL=https://mnemo.example.com \
  -e MCP_DCR_SERVER_SECRET=<dcr-secret> \
  ghcr.io/n24q02m/mnemo-mcp:latest --http
```

The `SYNC_PASSPHRASE` env var lives ONLY in the container process — it
is hashed via Argon2id for any persisted `config.json` record. No
end-user input is needed for passport sync in S3 mode.

### Switching modes (local → prod migration)

1. Export current GDrive bundles:
   `config(action="export_passport")` → save `.mnemo` files.
2. Provision the S3 bucket + credentials and restart the container
   with the new env vars (above).
3. Import the bundle on the new container:
   `config(action="import_passport", from="s3")` after pushing the
   exported bundle to the bucket under `<prefix>/seq-NNNNNN.bin`.

The legacy `SYNC_BACKEND` env var is **deprecated** (2026-05-14) — the
field is kept for backward compat with persisted configs but is no
longer consulted by the scheduler or `sync_now` handlers.

## Bundle format

```
+------------------------+
| 4 bytes header_len     |
+------------------------+
| plaintext JSON header  |   {"version":2,"kdf":"argon2id",
| (auditable, no secret) |    "salt":"<hex>","aead":"aes-256-gcm",
+------------------------+    "nonce":"<hex>"}
| AES-256-GCM ciphertext |   associated_data = header bytes
| (manifest + rows)      |
+------------------------+
```

The header is plaintext on purpose: a backend operator (or anyone
inspecting an exported `.mnemo` file) can read the version + KDF
parameters without holding the passphrase. The ciphertext is opaque;
modifying any byte flips the GCM auth tag and decryption raises
`InvalidTag`.

## Encryption details

- **AEAD**: AES-256-GCM with a 12-byte random nonce per bundle.
- **KDF**: Argon2id with a 32-byte random salt per bundle, 3 iterations,
  4 lanes, 64 MiB memory cost (OWASP 2024 baseline for interactive use).
- **Authenticated AAD**: the plaintext header bytes are bound into the
  GCM tag, so tampering with version / salt / nonce also fails decryption.

The same `bundle.encode_bundle` / `decode_bundle` codec is used for both
delta and full bundles so the on-disk format is identical regardless of
sync mode.

## Passphrase lifecycle

1. **Set once via the relay form** (HTTP mode) or `SYNC_PASSPHRASE` env
   var (stdio mode).
2. **Argon2id-hashed** by `credential_state._harden_passphrase` before
   persistence. Only the hash (`SYNC_PASSPHRASE_SALT` +
   `SYNC_PASSPHRASE_HASH`) lands in `config.json`. The raw passphrase
   never touches disk.
3. **Verified** on each sync via `bundle.verify_passphrase` (constant-
   time `hmac.compare_digest`).
4. **Lost = unrecoverable.** There is no backdoor. If you forget your
   passphrase the past bundles cannot be decrypted; you must reset and
   start fresh. `config(action="reset_sync", confirm=true)` clears local
   state without touching remote bundles.

This is by design: a recovery path would also let an attacker decrypt
your bundles if they obtained either backend access or `config.json`.

## Delta vs full sync

The orchestrator picks the right mode automatically per cycle:

- **Delta** (common case): collect rows whose `updated_at` is newer than
  the last sync timestamp -> encrypted bundle -> push at
  `local_cursor + 1`. Fast, small.
- **Full pull + merge + full push** (sequence gap): when another machine
  pushed in between (`remote_seq > local_cursor + 1`), pull the latest
  full passport, merge per-row LWW, then upload a consolidated bundle at
  `remote_seq + 1`.

LWW means: for each incoming row, the higher `updated_at` wins. When the
local row is newer, the remote row is skipped AND a row is written to
the `sync_overrides` audit table so divergence is never silently lost.

## Bootstrap a new machine

Use the `passport-bootstrap` skill:

1. Install mnemo-mcp.
2. Configure relay form (HTTP) or env vars (stdio) with your S3 / GDrive
   credentials AND your passphrase.
3. Trigger `config(action="import_passport", key="s3")` (or `"gdrive"`).
4. Verify `total_memories` via `config(action="status")`.

Anti-pattern: do NOT run `config(action="sync_now")` BEFORE the import.
That would push your empty local DB on top of the remote and the remote
would LWW-overwrite other machines' state on their next sync.

## Recovery FAQ

**Q: I forgot my passphrase. Can I recover?**
No. The Argon2id parameters are tuned to make brute-force
prohibitively expensive. By design.

**Q: I changed my passphrase. Are my old bundles still readable?**
Each bundle embeds its own salt + the passphrase used at encode time.
Old bundles need the old passphrase; new bundles need the new one. There
is no passphrase-rotation tool yet.

**Q: Can I have different passphrases for S3 vs GDrive?**
Moot under XOR semantics (2026-05-14): a single deployment runs ONE
backend, so the passphrase belongs to that backend's bundles. If you
need bundles encrypted under separate keys, run two separate deployments
(one S3, one GDrive) each with its own `SYNC_PASSPHRASE`.

**Q: How do I migrate from the legacy GDrive sync (DB-file copy) to
passport sync?**
Both modes coexist on the same OAuth token. Set `SYNC_PASSPHRASE` and
trigger `config(action="sync_now")` -- this writes a v2 passport bundle
to `<sync_folder>/passport/seq-NNNNNN.bin` alongside the legacy DB-file
copy. The DB-file path is deprecated and will be removed in a future
release.

**Q: My passport `.mnemo` file is huge. Why?**
Bundles include the full memory text (compressed when an LLM provider is
available). With cloud embeddings enabled the bundle also carries
`embeddings.bin`, which roughly triples the size. Argon2id + AES-256-GCM
both add minimal overhead (<1% over plaintext payload).
