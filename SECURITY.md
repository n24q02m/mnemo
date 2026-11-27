# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.x.x   | :white_check_mark: |
| < 2.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, please **DO NOT** create a public issue.

Instead, please email: **quangminh2402.dev@gmail.com**

Include:

1. Detailed description of the vulnerability
2. Steps to reproduce
3. Potential impact
4. Suggested fix (if any)

You will receive acknowledgment within 48 hours.

## Security Best Practices

When using mnemo:

- **Never commit API keys** to version control
- Use environment variables or secure secret management
- Keep dependencies updated
- Review imported JSONL data before processing
- Database files hold stored memories in plaintext unless encryption at
  rest is on. Set `MNEMO_ENCRYPTION_KEY` (and run `n24q02m-mnemo encrypt`
  for an existing store) to store memory text, tags, source and subject
  AES-256-GCM encrypted. Embedding vectors, metadata such as categories and
  timestamps, and text sent to provider cells stay unencrypted; see
  [Encryption at rest](README.md#encryption-at-rest)
- The backup written by `n24q02m-mnemo encrypt` is plaintext, and so is
  every `<store>.bak.*` file next to a store that was ever plaintext: the
  copies schema migrations take before they run, including the ones left by
  earlier upgrades. `encrypt` lists them all; delete them securely once the
  encrypted store has been checked
- The `encrypt` backup is created with mode 0o600 (read and write for its
  owner only). That mode has no effect on Windows, where the file gets the
  permissions of its folder, so keep the store folder private there
- `encrypt` runs `VACUUM` and truncates the WAL, but the filesystem or an
  SSD can still hold old copies of plaintext pages (journaling,
  copy-on-write, snapshots, wear levelling). Removing those remnants is out
  of scope; turn encryption on before storing anything, or use full-disk
  encryption, when that matters
- The `memory_audit` table is not encrypted. Nothing writes to it yet; once
  a release records changes there, its state hashes and `commit_sha` values
  are stored in plaintext
- Keep the encryption key outside the store, in a secret manager; a lost
  key cannot be recovered
