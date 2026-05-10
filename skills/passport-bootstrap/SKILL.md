---
name: passport-bootstrap
description: Use when the user installs mnemo-mcp on a fresh machine and wants to restore prior memory state from S3 or Google Drive (Phase 2 passport sync). Triggers on phrases like "set up mnemo on this machine", "restore my memory passport", "import passport", "bootstrap mnemo", or when the user says they got a new laptop / VM and wants their memories back.
argument-hint: "[backend: s3 | gdrive]"
---

# Passport Bootstrap

Restore an encrypted memory passport from a configured backend so a
fresh mnemo-mcp install picks up the user's full memory history.

## When to Use

Trigger on explicit signals:

- "set up mnemo on this machine"
- "restore my passport" / "import my memory passport"
- "bootstrap mnemo on this laptop / VM"
- New-machine context: "I just installed mnemo on a new device"
- Recovery context: "I lost my memories, can you restore from S3?"

Do NOT trigger when the user is on an already-configured machine
(check `config(action="status")` first - if `total_memories > 0`,
ask before importing because import LWW-merges and may NOT overwrite
local rows newer than the bundle).

## Workflow

### Step 1: Detect configured backend

Call `config(action="status")` and inspect the response. The default
backend is the first entry of `SYNC_BACKEND` env (defaults to
`gdrive`). If both `s3` and `gdrive` are configured, ask the user
which one to import from. If neither is configured, stop and tell the
user they need to run the relay form first
(`config(action="setup_start")` in HTTP mode, or set
`SYNC_S3_BUCKET` + `GOOGLE_DRIVE_CLIENT_ID` env vars in stdio mode).

### Step 2: Confirm passphrase

The bundle is AES-256-GCM-encrypted with an Argon2id-derived key from
the user's passphrase. The MCP server needs the RAW passphrase to
decrypt - the Argon2id hash stored in `config.enc` is verification-
only.

In stdio mode: instruct the user to set `SYNC_PASSPHRASE` env var
before running `mnemo-mcp` (or to relaunch with the env exported).

In HTTP mode: prompt the user to submit the relay form's passphrase
field again (the raw value is held in process memory only and is
cleared on restart - it is NEVER persisted).

### Step 3: Import the bundle

Call `config(action="import_passport", key="<backend>")` where
`<backend>` is `s3` or `gdrive`. The server pulls the latest bundle
from the chosen backend, decrypts with the supplied passphrase, and
applies each row via last-write-wins per row (local rows newer than
the bundle row are preserved + an audit row is written to
`sync_overrides`).

### Step 4: Verify

After the response lands, call `config(action="status")` again and
confirm `total_memories` matches expectations. If the response from
step 3 reports `inserted > 0` but `total_memories` did not move,
something else is wrong (caller should escalate, not silently
proceed).

## Failure Modes

- **"SYNC_PASSPHRASE not set"** -> Step 2 was skipped. Re-prompt for
  the passphrase, do NOT pick a default value.
- **"Passphrase mismatch or tampered bundle"** -> wrong passphrase,
  OR the bundle was modified at rest. Generic message by design (no
  passphrase oracle). Tell the user to double-check the passphrase;
  if confirmed correct, the bundle may need re-upload from a clean
  source.
- **"no_passport"** -> the backend bucket / folder is empty. Either
  the user has never run `config(action="sync_now")` from another
  machine, or the bucket name in the relay form was wrong. Ask them
  to verify on the source machine.
- **`KeyError` on backend name** -> backend isn't registered. Means
  `SYNC_S3_BUCKET` is empty (for s3) or the gdrive token is missing.
  Run the relay form to populate.

## Anti-Patterns

- Do NOT call `config(action="sync_now")` before import - that would
  push the empty local DB on top of the remote, deleting other
  machines' state.
- Do NOT call `memory(action="import", data=...)` - that imports
  Phase 1 JSONL files, NOT Phase 2 encrypted passport bundles.
- Do NOT proceed silently when the user supplied no passphrase.
  Importing yields cryptic "Passphrase mismatch" errors instead of
  the cleaner "passphrase missing" pre-flight check.
