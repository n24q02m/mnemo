# Passport Sync

Mnemo Phase 2 introduces **passport sync**: an end-to-end-encrypted memory
backup / restore loop that lets you carry your full memory history across
machines without exposing plaintext to the storage backend.

## Concept

A *passport* is a single self-contained encrypted bundle that snapshots
your memory store (manifest + memory rows + entity / edge sections + room
for Phase 3 embeddings). The bundle is opaque to whichever backend stores
it -- Cloudflare R2, AWS S3, Backblaze B2, MinIO, or Google Drive only ever
see ciphertext.

When you bootstrap a fresh machine you supply your passphrase, point at
your backend, and `config(action="import_passport")` rehydrates the local
SQLite store with the full passport content.

## Backend choice

| Backend | Pros | Cons |
|---|---|---|
| **S3** (R2 / B2 / MinIO / AWS) | Cheap (CF R2 free tier covers most users), portable, no API rate limits, easy multi-region | Requires you to register a bucket + IAM key |
| **Google Drive** | Zero infra setup if you already have a Google account, OAuth Device Code flow | API quotas, slower for large bundles, ties you to Google |

You can configure both: `SYNC_BACKEND="s3,gdrive"` will mirror passport
pushes across both backends per scheduler tick.

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
   `SYNC_PASSPHRASE_HASH`) lands in `config.enc`. The raw passphrase
   never touches disk.
3. **Verified** on each sync via `bundle.verify_passphrase` (constant-
   time `hmac.compare_digest`).
4. **Lost = unrecoverable.** There is no backdoor. If you forget your
   passphrase the past bundles cannot be decrypted; you must reset and
   start fresh. `config(action="reset_sync", confirm=true)` (Phase 3) will
   clear local state without touching remote bundles.

This is by design: a recovery path would also let an attacker decrypt
your bundles if they obtained either backend access or `config.enc`.

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

Use the `passport-bootstrap` skill (Phase 2 trinity addition):

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
is no rotation tool yet (Phase 3 may add one).

**Q: Can I have different passphrases for S3 vs GDrive?**
Not currently. Both backends share `SYNC_PASSPHRASE` at the orchestrator
level. If you need separate keys, use only one backend at a time.

**Q: How do I migrate from Phase 1 GDrive sync (DB-file copy) to Phase 2
passport sync?**
Both modes coexist on the same OAuth token. Set `SYNC_PASSPHRASE` and
trigger `config(action="sync_now")` -- this writes a v2 passport bundle
to `<sync_folder>/passport/seq-NNNNNN.bin` alongside the legacy DB-file
copy. Phase 3 will deprecate the DB-file path.

**Q: My passport `.mnemo` file is huge. Why?**
Phase 2 bundles include the full memory text (compressed when LLM
available). Phase 3 will add embeddings.bin which roughly triples the
size for users with cloud embeddings enabled. Argon2id + AES-256-GCM
both add minimal overhead (<1% over plaintext payload).
