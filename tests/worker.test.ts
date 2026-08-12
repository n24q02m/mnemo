import { describe, expect, it } from 'vitest'
import worker, { CONTAINER_ENV_KEYS, OUTBOUND_BY_HOST } from '../src/worker'
// tsconfig.json's `types` deliberately lists only `@cloudflare/workers-types`
// (no `@types/node`) so src/worker.ts type-checks against the workerd runtime,
// not Node globals -- adding `@types/node` would blur that boundary for the
// whole program (TS ambient types are program-wide, not file-scoped). This
// file runs under plain Node via vitest and only needs one function from it.
// @ts-expect-error -- no `@types/node`; see comment above
import { readFileSync } from 'node:fs'

function fakeEnv() {
  const kv = new Map<string, string>()
  return {
    KV: {
      get: async (k: string) => (kv.has(k) ? kv.get(k)! : null),
      put: async (k: string, v: string) => void kv.set(k, v),
      delete: async (k: string) => void kv.delete(k),
    },
    D1: {
      prepare: (sql: string) => ({
        bind: (..._p: unknown[]) => ({ all: async () => ({ results: [{ ok: 1, sql }] }) }),
      }),
    },
    VECTORIZE: {
      upsert: async () => ({ mutationId: 'm1' }),
      query: async () => ({ matches: [{ id: 'a', score: 0.9 }] }),
      deleteByIds: async () => ({ mutationId: 'm2' }),
    },
  }
}

// Invoke an outbound handler DIRECTLY (the production path is the container proxy
// via MnemoContainer.outboundByHost; the handlers are NOT reachable through the
// public `fetch` entrypoint, so tests exercise them through the exported registry).
const kvH = OUTBOUND_BY_HOST['kv.internal']!
const d1H = OUTBOUND_BY_HOST['d1.internal']!
const vectorizeH = OUTBOUND_BY_HOST['vectorize.internal']!
// Handlers also take an OutboundHandlerContext third arg (containerId/className);
// unused by these handlers, only needed to satisfy the call signature in tests.
const ctx = { containerId: 'test', className: 'MnemoContainer' } as never

describe('outbound handlers', () => {
  it('KV get 404 then put then get 200', async () => {
    const env = fakeEnv()
    let res = await kvH(new Request('http://kv.internal/mnemo%2Fconfig'), env as never, ctx)
    expect(res.status).toBe(404)
    res = await kvH(new Request('http://kv.internal/mnemo%2Fconfig', { method: 'PUT', body: 'blob' }), env as never, ctx)
    expect(res.status).toBe(200)
    res = await kvH(new Request('http://kv.internal/mnemo%2Fconfig'), env as never, ctx)
    expect(await res.text()).toBe('blob')
  })

  it('D1 query uses prepared statement', async () => {
    const env = fakeEnv()
    const res = await d1H(
      new Request('http://d1.internal/query', { method: 'POST', body: JSON.stringify({ sql: 'SELECT 1', params: [] }) }),
      env as never,
      ctx,
    )
    const body = (await res.json()) as { results: unknown[] }
    expect(body.results.length).toBe(1)
  })

  it('Vectorize query returns matches', async () => {
    const env = fakeEnv()
    const res = await vectorizeH(
      new Request('http://vectorize.internal/query', { method: 'POST', body: JSON.stringify({ vector: [0.1], topK: 1 }) }),
      env as never,
      ctx,
    )
    const body = (await res.json()) as { matches: unknown[] }
    expect(body.matches.length).toBe(1)
  })

  it('Vectorize deleteByIds returns mutationId', async () => {
    const env = fakeEnv()
    const res = await vectorizeH(
      new Request('http://vectorize.internal/deleteByIds', { method: 'POST', body: JSON.stringify({ ids: ['u1:m1'] }) }),
      env as never,
      ctx,
    )
    const body = (await res.json()) as { mutationId: string }
    expect(body.mutationId).toBe('m2')
  })

  it('KV readiness probe: GET __ready -> {ready:true}', async () => {
    const env = fakeEnv()
    const res = await kvH(new Request('http://kv.internal/__ready'), env as never, ctx)
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ ready: true })
  })

  it('KV readiness probe does not shadow a real missing key', async () => {
    const env = fakeEnv()
    // a real key that happens to be absent still 404s (the probe is the reserved __ready only)
    const res = await kvH(new Request('http://kv.internal/mnemo%2Fsubs%2Fu1%2Fconfig'), env as never, ctx)
    expect(res.status).toBe(404)
  })
})

describe('public fetch entrypoint does NOT expose outbound handlers (security)', () => {
  it('a public request with an internal hostname is NOT serviced by a handler', async () => {
    const env = fakeEnv() // no MNEMO binding -> DO routing path returns 404
    // Even if an external caller spoofs the hostname to kv.internal, the public
    // fetch must NOT read/write the credential KV — it only routes to the DO.
    const res = await worker.fetch(new Request('http://kv.internal/mnemo%2Fconfig'), env as never)
    expect(res.status).toBe(404)
    expect(await res.text()).toBe('not found')
  })
})

describe('edge auth gate (/mcp)', () => {
  function envWithDoSpy() {
    const fetchCalls: Request[] = []
    return {
      fetchCalls,
      env: {
        MNEMO: {
          idFromName: (n: string) => ({ name: n }),
          get: (_id: unknown) => ({
            fetch: async (r: Request) => {
              fetchCalls.push(r)
              return new Response('routed', { status: 200 })
            },
          }),
        },
      },
    }
  }

  it('POST /mcp with no Authorization -> 401, stub never called', async () => {
    const { fetchCalls, env } = envWithDoSpy()
    const res = await worker.fetch(new Request('https://mnemo.n24q02m.com/mcp', { method: 'POST' }), env as never)
    expect(res.status).toBe(401)
    expect(res.headers.get('WWW-Authenticate')).toMatch(
      /^Bearer resource_metadata="https:\/\/[^"]+\/\.well-known\/oauth-protected-resource"$/,
    )
    expect(await res.text()).toBe('')
    expect(fetchCalls.length).toBe(0)
  })

  it('OPTIONS /mcp with no Authorization -> 401, stub never called', async () => {
    const { fetchCalls, env } = envWithDoSpy()
    const res = await worker.fetch(new Request('https://mnemo.n24q02m.com/mcp', { method: 'OPTIONS' }), env as never)
    expect(res.status).toBe(401)
    expect(fetchCalls.length).toBe(0)
  })

  it('POST /mcp with Authorization: Bearer anything -> stub called exactly once', async () => {
    const { fetchCalls, env } = envWithDoSpy()
    const res = await worker.fetch(
      new Request('https://mnemo.n24q02m.com/mcp', { method: 'POST', headers: { authorization: 'Bearer anything' } }),
      env as never,
    )
    expect(res.status).toBe(200)
    expect(fetchCalls.length).toBe(1)
  })

  it('GET /authorize with no Authorization -> passes through, stub called', async () => {
    const { fetchCalls, env } = envWithDoSpy()
    const res = await worker.fetch(new Request('https://mnemo.n24q02m.com/authorize?foo=1'), env as never)
    expect(res.status).toBe(200)
    expect(fetchCalls.length).toBe(1)
  })
})

describe('standing GET /mcp SSE stream declined at the edge (idle-cost fix)', () => {
  function envWithDoSpy() {
    const fetchCalls: Request[] = []
    return {
      fetchCalls,
      env: {
        MNEMO: {
          idFromName: (n: string) => ({ name: n }),
          get: (_id: unknown) => ({
            fetch: async (r: Request) => {
              fetchCalls.push(r)
              return new Response('routed', { status: 200 })
            },
          }),
        },
      },
    }
  }

  it('GET /mcp with Authorization -> 405, Allow: POST, DELETE, stub never called', async () => {
    const { fetchCalls, env } = envWithDoSpy()
    const res = await worker.fetch(
      new Request('https://mnemo.n24q02m.com/mcp', { method: 'GET', headers: { authorization: 'Bearer x' } }),
      env as never,
    )
    expect(res.status).toBe(405)
    expect(res.headers.get('Allow')).toBe('POST, DELETE')
    expect(fetchCalls.length).toBe(0)
  })

  it('GET /mcp/sub-path with Authorization -> 405, stub never called', async () => {
    const { fetchCalls, env } = envWithDoSpy()
    const res = await worker.fetch(
      new Request('https://mnemo.n24q02m.com/mcp/sub', { method: 'GET', headers: { authorization: 'Bearer x' } }),
      env as never,
    )
    expect(res.status).toBe(405)
    expect(fetchCalls.length).toBe(0)
  })

  it('GET /mcp with no Authorization -> still 401 (bearer gate runs before the 405 decline)', async () => {
    const { fetchCalls, env } = envWithDoSpy()
    const res = await worker.fetch(new Request('https://mnemo.n24q02m.com/mcp', { method: 'GET' }), env as never)
    expect(res.status).toBe(401)
    expect(fetchCalls.length).toBe(0)
  })
})

// Minimal JSONC -> JSON: strips `//` line comments and `/* */` block comments
// while respecting string literals, so values like "http://kv.internal" survive
// intact. wrangler*.jsonc files are read for real here (not hardcoded) so this
// test actually catches drift instead of restating CONTAINER_ENV_KEYS.
function stripJsonComments(src: string): string {
  let out = ''
  let inString = false
  let inLineComment = false
  let inBlockComment = false
  for (let i = 0; i < src.length; i++) {
    const c = src[i]
    const next = src[i + 1]
    if (inLineComment) {
      if (c === '\n') {
        inLineComment = false
        out += c
      }
      continue
    }
    if (inBlockComment) {
      if (c === '*' && next === '/') {
        inBlockComment = false
        i++
      }
      continue
    }
    if (inString) {
      out += c
      if (c === '\\') {
        out += next
        i++
        continue
      }
      if (c === '"') inString = false
      continue
    }
    if (c === '"') {
      inString = true
      out += c
      continue
    }
    if (c === '/' && next === '/') {
      inLineComment = true
      i++
      continue
    }
    if (c === '/' && next === '*') {
      inBlockComment = true
      i++
      continue
    }
    out += c
  }
  return out
}

// Path is relative to the repo root, which is the cwd `vitest` runs from
// (package.json's `test:worker` script and the CI step both invoke it from
// the repo root, never from `tests/`).
function readWranglerVarKeys(repoRootRelPath: string): string[] {
  const parsed = JSON.parse(stripJsonComments(readFileSync(repoRootRelPath, 'utf8'))) as { vars?: Record<string, unknown> }
  return Object.keys(parsed.vars ?? {})
}

// A key declared in wrangler `vars` but missing from CONTAINER_ENV_KEYS is
// silently dropped by pickContainerEnv -- the container just runs with whatever
// default core-py falls back to, with no error anywhere. This reads all three
// wrangler*.jsonc files for real (never hardcodes their `vars`) so it actually
// fails when someone adds a wrangler var without wiring it into the Worker.
describe('CONTAINER_ENV_KEYS covers every wrangler `vars` key', () => {
  const wranglerFiles = ['wrangler.jsonc', 'wrangler.deploy.jsonc', 'wrangler.deploy.template.jsonc']

  it('every `vars` key in each wrangler*.jsonc is forwarded by CONTAINER_ENV_KEYS', () => {
    const forwarded = new Set<string>(CONTAINER_ENV_KEYS)
    const missing: string[] = []
    for (const file of wranglerFiles) {
      for (const key of readWranglerVarKeys(file)) {
        if (!forwarded.has(key)) missing.push(`${file}: ${key}`)
      }
    }
    expect(missing).toEqual([])
  })
})

describe('container recovery controls', () => {
  it('forwards the persisted-vector reindex gate into the Python process', () => {
    expect(CONTAINER_ENV_KEYS).toContain('REINDEX_ON_MODEL_CHANGE')
  })

  it('disables legacy Google Drive sync in every Cloudflare deploy vars file', () => {
    for (const file of ['wrangler.jsonc', 'wrangler.deploy.template.jsonc']) {
      const parsed = JSON.parse(stripJsonComments(readFileSync(file, 'utf8'))) as { vars?: Record<string, unknown> }
      expect(parsed.vars?.SYNC_ENABLED, `${file}: SYNC_ENABLED`).toBe('false')
    }
  })

  it('enables persisted-vector recovery in every Cloudflare deploy vars file', () => {
    for (const file of ['wrangler.jsonc', 'wrangler.deploy.template.jsonc']) {
      const parsed = JSON.parse(stripJsonComments(readFileSync(file, 'utf8'))) as { vars?: Record<string, unknown> }
      expect(parsed.vars?.REINDEX_ON_MODEL_CHANGE, `${file}: REINDEX_ON_MODEL_CHANGE`).toBe('true')
    }
  })
})
