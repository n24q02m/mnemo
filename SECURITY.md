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
- The backup written by `n24q02m-mnemo encrypt` is plaintext: delete it
  securely once the encrypted store has been checked
- Keep the encryption key outside the store, in a secret manager; a lost
  key cannot be recovered
