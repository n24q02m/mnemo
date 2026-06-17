import { describe, expect, it } from 'vitest'
import worker, { MnemoContainer, OUTBOUND_BY_HOST } from '../src/worker'

// Invoke an outbound handler DIRECTLY. The production path is the container proxy
// via MnemoContainer.outboundByHost; the handlers are deliberately NOT reachable
// through the public `fetch` entrypoint, so tests exercise them through the
// exported registry instead of routing an internal-host request publicly.
//
// `OutboundHandler` is typed `(req, env, ctx)`; the handlers never read `ctx` (the
// container proxy supplies it in prod), so bind a 2-arg adapter for the call sites.
type Handler = (typeof OUTBOUND_BY_HOST)[string]
const bind2 = (h: Handler) => (req: Request, env: unknown) => h(req, env as never, undefined as never)
const kvH = bind2(OUTBOUND_BY_HOST['kv.internal']!)
const d1H = bind2(OUTBOUND_BY_HOST['d1.internal']!)
const vectorizeH = bind2(OUTBOUND_BY_HOST['vectorize.internal']!)

function fakeEnv() {
  const kv = new Map<string, ArrayBuffer>()
  return {
    KV: {
      // mnemo credential/token blobs are binary (nonce + AES-GCM ciphertext); the
      // handler reads/writes them as ArrayBuffer, so the fake mirrors that shape.
      get: async (k: string, _type?: string) => kv.get(k) ?? null,
      put: async (k: string, v: ArrayBuffer) => void kv.set(k, v),
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
      deleteByIds: async (ids: string[]) => ({ mutationId: `del-${ids.length}` }),
    },
  }
}

describe('outbound handler registration (footgun #1: assignment, not class field)', () => {
  it('OUTBOUND_BY_HOST exports exactly the three internal hosts', () => {
    expect(Object.keys(OUTBOUND_BY_HOST).sort()).toEqual(['d1.internal', 'kv.internal', 'vectorize.internal'])
  })

  it('MnemoContainer.outboundByHost is populated via the inherited setter', () => {
    // A `static outboundByHost = {...}` class FIELD would bypass the setter and
    // leave the package registry empty -> kv.internal falls through to public DNS.
    // Reading it back proves the assignment hit the setter.
    const registered = (MnemoContainer as unknown as { outboundByHost?: Record<string, unknown> }).outboundByHost
    expect(registered).toBeDefined()
    expect(Object.keys(registered ?? {})).toContain('kv.internal')
    expect(Object.keys(registered ?? {})).toContain('d1.internal')
    expect(Object.keys(registered ?? {})).toContain('vectorize.internal')
  })
})

describe('kv outbound', () => {
  it('round-trips a binary blob via arrayBuffer (GET 404 -> PUT -> GET 200)', async () => {
    const env = fakeEnv()
    let res = await kvH(new Request('http://kv.internal/mnemo%2Fconfig'), env as never)
    expect(res.status).toBe(404)

    const bytes = new Uint8Array([0, 255, 12, 99]).buffer
    res = await kvH(new Request('http://kv.internal/mnemo%2Fconfig', { method: 'PUT', body: bytes }), env as never)
    expect(res.status).toBe(200)

    res = await kvH(new Request('http://kv.internal/mnemo%2Fconfig'), env as never)
    expect(res.status).toBe(200)
    expect(new Uint8Array(await res.arrayBuffer())).toEqual(new Uint8Array([0, 255, 12, 99]))
  })

  it('readiness probe: GET __ready -> {ready:true}', async () => {
    const env = fakeEnv()
    const res = await kvH(new Request('http://kv.internal/__ready'), env as never)
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ ready: true })
  })

  it('readiness probe does not shadow a real missing key', async () => {
    const env = fakeEnv()
    const res = await kvH(new Request('http://kv.internal/mnemo%2Fsubs%2Fu1%2Fconfig'), env as never)
    expect(res.status).toBe(404)
  })

  it('DELETE removes a stored key', async () => {
    const env = fakeEnv()
    await kvH(new Request('http://kv.internal/mnemo%2Fconfig', { method: 'PUT', body: new Uint8Array([1]).buffer }), env as never)
    const del = await kvH(new Request('http://kv.internal/mnemo%2Fconfig', { method: 'DELETE' }), env as never)
    expect(del.status).toBe(200)
    const got = await kvH(new Request('http://kv.internal/mnemo%2Fconfig'), env as never)
    expect(got.status).toBe(404)
  })
})

describe('d1 outbound', () => {
  it('POST /query uses a prepared statement', async () => {
    const env = fakeEnv()
    const res = await d1H(
      new Request('http://d1.internal/query', { method: 'POST', body: JSON.stringify({ sql: 'SELECT 1', params: [] }) }),
      env as never,
    )
    const body = (await res.json()) as { results: unknown[] }
    expect(body.results.length).toBe(1)
  })
})

describe('vectorize outbound', () => {
  it('POST /query returns matches', async () => {
    const env = fakeEnv()
    const res = await vectorizeH(
      new Request('http://vectorize.internal/query', { method: 'POST', body: JSON.stringify({ vector: [0.1], topK: 1 }) }),
      env as never,
    )
    const body = (await res.json()) as { matches: unknown[] }
    expect(body.matches.length).toBe(1)
  })

  it('POST /deleteByIds forwards ids to the binding (delete()/reindex path)', async () => {
    const env = fakeEnv()
    const res = await vectorizeH(
      new Request('http://vectorize.internal/deleteByIds', {
        method: 'POST',
        body: JSON.stringify({ ids: ['user1:mid-1', 'user1:mid-2'] }),
      }),
      env as never,
    )
    expect(await res.json()).toEqual({ mutationId: 'del-2' })
  })

  it('GET answers the readiness probe', async () => {
    const env = fakeEnv()
    const res = await vectorizeH(new Request('http://vectorize.internal/'), env as never)
    expect(await res.json()).toEqual({ ready: true })
  })
})

describe('public fetch entrypoint does NOT expose outbound handlers (security: "không mở cửa nhà")', () => {
  it('a public request spoofing an internal hostname is NOT serviced by a handler', async () => {
    const env = fakeEnv() // no MNEMO binding -> DO routing path returns 404
    // Even if an external caller spoofs the hostname to kv.internal, the public
    // fetch must NOT read/write the credential KV -- it only routes to the DO.
    const res = await worker.fetch(new Request('http://kv.internal/mnemo%2Fconfig'), env as never)
    expect(res.status).toBe(404)
    expect(await res.text()).toBe('not found')
  })
})

describe('single-user DO contract (E.2) + per-sub isolation', () => {
  function envWithDoSpy() {
    const seen: string[] = []
    return {
      seen,
      env: {
        MNEMO: {
          idFromName: (n: string) => {
            seen.push(n)
            return { name: n }
          },
          get: (_id: unknown) => ({ fetch: async () => new Response('routed', { status: 200 }) }),
        },
      },
    }
  }

  it('no Bearer token -> routes to the "default" DO', async () => {
    const { seen, env } = envWithDoSpy()
    const res = await worker.fetch(new Request('https://mnemo.n24q02m.com/mcp'), env as never)
    expect(res.status).toBe(200)
    expect(seen).toEqual(['default'])
  })

  it('Bearer token without sub -> routes to the "default" DO', async () => {
    const { seen, env } = envWithDoSpy()
    const jwt = `h.${btoa(JSON.stringify({ aud: 'x' }))}.s`
    await worker.fetch(
      new Request('https://mnemo.n24q02m.com/mcp', { headers: { authorization: `Bearer ${jwt}` } }),
      env as never,
    )
    expect(seen).toEqual(['default'])
  })

  it('Bearer token with sub -> routes to that sub DO (per-user isolation)', async () => {
    const { seen, env } = envWithDoSpy()
    const payload = btoa(JSON.stringify({ sub: 'user1' }))
    const res = await worker.fetch(
      new Request('https://mnemo.n24q02m.com/mcp', { headers: { authorization: `Bearer h.${payload}.s` } }),
      env as never,
    )
    expect(res.status).toBe(200)
    expect(seen).toContain('user1')
  })
})
