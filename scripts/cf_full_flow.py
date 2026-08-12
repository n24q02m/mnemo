"""CF mnemo-mcp live OAuth full-flow self-test harness.

Drives the deployed mnemo-mcp Cloudflare Worker (Worker + per-sub Container + KV +
D1 + Vectorize) end-to-end against a public endpoint. mnemo is a LOCAL-FORM server
(like wet/imagine/email, NOT delegated like notion): the /authorize gate is just
the relay password, so the whole flow is fully autonomous -- no third-party consent.

Flow (authorization_code + PKCE, DCR public client; ported verbatim from the
mnemo/imagine/email CF harnesses):
  1. DCR register   -- POST /register (RFC 7591) -> client_id
  2. password-grant -- GET /authorize -> POST /login (Gate A relay password) -> form
  3. save creds     -- POST /authorize?nonce=... {provider key + routing} (retry-on-500
                       for the E.1 outbound-interception race). Mnemo's credential
                       gate requires >=1 provider key in the per-sub vault; the
                       harness also submits the model and endpoint routing explicitly.
  4. token          -- POST /token (code + verifier) -> bearer JWT
  5. tool call      -- config(status) + unique add/search/delete round-trip and a
                       multi-candidate semantic/rerank probe over D1/Vectorize.

Secrets from env: Gate A login password MCP_RELAY_PASSWORD (or RELAY_PW) from skret
/oci-vm-prod/prod (infra-shared); default provider values come from the configured
per-sub relay. With --cohere-cf-gateway, CF_AIG_BASE and CF_AIG_TOKEN come from the
existing /n24q02m/dev namespace and are mapped to the approved Cohere gateway route.

Run modes:
  (default)            full flow: config(status) + search and multi-candidate
                       semantic/rerank probe, asserting real results.
  --save-only          configure one sub (submit provider key) + dump the token
                       (recreate-gate setup half of the state-survives-recreate test).
  --auth-only          replay the SAME token (same sub) and search again WITHOUT
                       re-saving (recreate-gate verify: the sub vault survived KV).
  --backfill           configure the sub through the relay, then run the bounded
                       embedding backfill over the deployed D1/Vectorize path.
  --two-sub-isolation  two distinct subs; sub B must not find sub A's unique marker
                       before B creates and searches its own marker.

Examples:
  skret run -e prod --path=/oci-vm-prod/prod -- \
    skret run -e prod --path=/mnemo-mcp/prod -- \
      python scripts/cf_full_flow.py
  ... -- python scripts/cf_full_flow.py --endpoint https://mnemo.n24q02m.com
  ... -- python scripts/cf_full_flow.py --save-only
  ... -- python scripts/cf_full_flow.py --auth-only
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json as _json
import os
import re
import secrets
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ENDPOINT = "https://mnemo.n24q02m.com"

# Stable prefix retained for recognizable harness data; each probe appends a
# cryptographically random suffix so independent runs cannot deduplicate.
MARKER = "cf-canary-probe-mnemo"


def _configure_cohere_cf_gateway() -> None:
    """Configure the approved Cohere-through-CF-AI-Gateway BYOK route.

    The deployed relay must receive the gateway token as ``COHERE_API_KEY`` so
    LiteLLM sends it as the gateway ``Authorization`` credential.  The
    gateway then selects Cohere from the explicit endpoint paths.  Clear
    competing provider/model values first so a stale local or skret export
    cannot silently route the probe to Jina or another provider.
    """
    base = os.environ.get("CF_AIG_BASE", "").strip().rstrip("/")
    token = os.environ.get("CF_AIG_TOKEN", "").strip()
    if not base or not token:
        raise SystemExit(
            "--cohere-cf-gateway requires non-empty CF_AIG_BASE and CF_AIG_TOKEN "
            "from the existing skret namespace."
        )

    for env_name in (
        "JINA_AI_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "XAI_API_KEY",
        "COHERE_API_KEY",
        "EMBEDDING_MODELS",
        "EMBEDDING_API_BASE",
        "RERANK_MODELS",
        "RERANK_API_BASE",
        "LLM_MODELS",
        "LLM_API_BASE",
    ):
        os.environ.pop(env_name, None)

    os.environ.update(
        {
            "COHERE_API_KEY": token,
            "EMBEDDING_MODELS": "cohere/embed-v4.0",
            "EMBEDDING_API_BASE": f"{base}/cohere/v2/embed",
            "RERANK_MODELS": "cohere/rerank-v4.0-fast",
            "RERANK_API_BASE": f"{base}/cohere",
        }
    )


def _password() -> str:
    pw = os.environ.get("RELAY_PW") or os.environ.get("MCP_RELAY_PASSWORD")
    if not pw:
        raise SystemExit(
            "MCP_RELAY_PASSWORD (or RELAY_PW) is required for the password-grant "
            "login gate. It lives in skret /oci-vm-prod/prod (infra-shared), NOT "
            "/mnemo-mcp/prod -- compose both namespaces."
        )
    return pw


def _creds() -> dict[str, str]:
    """Build the per-sub provider and model-routing form payload."""
    creds: dict[str, str] = {}
    for env_name in (
        "JINA_AI_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "COHERE_API_KEY",
        "XAI_API_KEY",
    ):
        v = os.environ.get(env_name)
        if v:
            creds[env_name] = v
    for env_name in (
        "EMBEDDING_MODELS",
        "EMBEDDING_API_BASE",
        "RERANK_MODELS",
        "RERANK_API_BASE",
        "LLM_MODELS",
        "LLM_API_BASE",
    ):
        v = os.environ.get(env_name)
        if v:
            creds[env_name] = v
    if not creds:
        raise SystemExit(
            "No provider key in env (JINA_AI_API_KEY / GEMINI_API_KEY / "
            "OPENAI_API_KEY / COHERE_API_KEY). Provide the relay-managed per-sub "
            "provider key through skret."
        )
    return creds


class _SaveRetry(Exception):
    pass


def get_token(endpoint: str, creds: dict[str, str], *, save_retries: int = 8) -> str:
    """Run the full OAuth flow, retrying on a transient 500 at the credential save
    step (CF Containers outbound-interception race on cold-started instances; E.1).
    Each retry restarts from DCR so the nonce is fresh. ``creds`` is the /authorize
    form payload (provider and routing settings are explicit for Mnemo)."""
    import httpx  # lazy: keep --help importable without httpx installed

    last: Exception | None = None
    for attempt in range(save_retries):
        try:
            return _get_token_once(httpx, endpoint, creds)
        except _SaveRetry as e:
            last = e
            print(
                f"get_token: save 500 (interception race), retry {attempt + 1}/{save_retries}"
            )
            time.sleep(3)
    raise RuntimeError(f"get_token failed after {save_retries} retries: {last}")


def _get_token_once(httpx, endpoint: str, creds: dict[str, str]) -> str:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    ru = "http://localhost:9999/cb"
    pw = _password()
    with httpx.Client(timeout=120, follow_redirects=False) as c:
        cid = c.post(
            f"{endpoint}/register",
            json={
                "client_name": "cf-verify",
                "redirect_uris": [ru],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": "offline_access",
            },
        ).json()["client_id"]
        az = c.get(
            f"{endpoint}/authorize",
            params={
                "response_type": "code",
                "client_id": cid,
                "redirect_uri": ru,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "st",
                "scope": "offline_access",
            },
        )
        nxt = urllib.parse.parse_qs(
            urllib.parse.urlparse(az.headers["location"]).query
        )["next"][0]
        lg = c.post(f"{endpoint}/login", data={"next": nxt, "password": pw})
        url = lg.headers["location"]
        url = url if url.startswith("http") else endpoint + url
        form_html = c.get(url).text
        m = re.search(r"/authorize\?nonce=([A-Za-z0-9_\-]+)", form_html)
        assert m, "nonce not found in form"
        nonce = m.group(1)
        sub = c.post(f"{endpoint}/authorize", params={"nonce": nonce}, json=creds)
        if sub.status_code == 500 and "save credentials" in sub.text:
            raise _SaveRetry(sub.text[:120])
        assert sub.status_code == 200, (sub.status_code, sub.text[:300])
        data = sub.json()
        assert data.get("ok"), data
        code = urllib.parse.parse_qs(urllib.parse.urlparse(data["redirect_url"]).query)[
            "code"
        ][0]
        tok = c.post(
            f"{endpoint}/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": ru,
                "client_id": cid,
                "code_verifier": verifier,
            },
        )
        assert tok.status_code == 200, (tok.status_code, tok.text[:300])
        return tok.json()["access_token"]


def _sub_of(token: str) -> str:
    payload = _json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    return payload.get("sub", "?")


async def _call(s, label, tool, args, *, retries=20, delay=8):
    """Call a tool, retrying while the sub is still propagating (KV cross-colo
    eventual consistency after the setup write; E.2). Returns the concatenated
    text payload, or None on give-up."""
    for i in range(retries):
        try:
            res = await s.call_tool(tool, args)
            txt = "".join(getattr(b, "text", "") for b in res.content)
            if "awaiting_setup" in txt or "Credentials not configured" in txt:
                print(f"{label}: awaiting_setup (KV propagating) try {i + 1}/{retries}")
                await asyncio.sleep(delay)
                continue
            print(f"{label} OK:", txt[:320].replace("\n", " "))
            return txt
        except Exception as e:
            print(f"{label} ERR:", repr(e)[:300])
            return None
    print(f"{label}: gave up after {retries} tries")
    return None


@dataclass(frozen=True)
class _SearchProbe:
    marker: str
    memory_id: str
    search_text: str | None


def _new_marker(scope: str = "roundtrip") -> str:
    return f"{MARKER}-{scope}-{secrets.token_hex(8)}"


def _tool_payload(txt: str | None, operation: str) -> dict:
    assert txt is not None, f"{operation} returned no payload"
    try:
        payload = _json.loads(txt)
    except _json.JSONDecodeError as exc:
        raise AssertionError(
            f"{operation} returned non-JSON payload: {txt[:300]}"
        ) from exc
    assert isinstance(payload, dict), f"{operation} returned a non-object payload"
    assert not payload.get("error"), f"{operation} returned an error: {txt[:300]}"
    return payload


def _memory_id(payload: dict, operation: str) -> str:
    memory_id = payload.get("id") or payload.get("memory_id")
    assert isinstance(memory_id, str) and memory_id, (
        f"{operation} did not return an exact memory id"
    )
    return memory_id


def _search_results(txt: str | None) -> list[dict]:
    payload = _tool_payload(txt, "search_memory")
    results = payload.get("results")
    assert isinstance(results, list), "search_memory did not return a results list"
    assert all(isinstance(result, dict) for result in results), (
        "search_memory returned a non-object result"
    )
    return results


def _assert_search_resolved(
    txt: str | None,
    marker: str = MARKER,
    memory_id: str | None = None,
) -> None:
    """Require the exact added memory and its unique marker in search results."""
    results = _search_results(txt)
    result_text = _json.dumps(results, ensure_ascii=False)
    assert any(
        (
            memory_id is None
            or result.get("id") == memory_id
            or result.get("memory_id") == memory_id
        )
        and marker in _json.dumps(result, ensure_ascii=False)
        for result in results
    ), f"search_memory did not return the added marker/id: {result_text[:300]}"
    print(
        "ASSERT OK: add_memory -> search_memory round-trip resolved over the CF deployment."
    )


def _assert_search_absent(txt: str | None, marker: str) -> None:
    """Require that search results contain no trace of a marker."""
    results = _search_results(txt)
    result_text = _json.dumps(results, ensure_ascii=False)
    assert marker not in result_text, (
        "isolation failure: search_memory returned sub A marker for sub B: "
        f"{result_text[:300]}"
    )
    print("ASSERT OK: sub B search did not return sub A marker.")


def _assert_rerank_payload(txt: str | None, memory_ids: list[str]) -> None:
    """Require a multi-result search to use both embedding and reranking."""
    payload = _tool_payload(txt, "search_memory(rerank)")
    assert payload.get("semantic") is True, (
        "multi-candidate search did not report semantic=true: "
        f"{_json.dumps(payload, ensure_ascii=False)[:400]}"
    )
    assert payload.get("reranked") is True, (
        "multi-candidate search did not report reranked=true: "
        f"{_json.dumps(payload, ensure_ascii=False)[:400]}"
    )
    results = _search_results(txt)
    result_ids = {result.get("id") or result.get("memory_id") for result in results}
    missing = [memory_id for memory_id in memory_ids if memory_id not in result_ids]
    assert not missing, (
        "multi-candidate search omitted exact probe ids: "
        f"{missing}; results={_json.dumps(results, ensure_ascii=False)[:400]}"
    )
    assert len(results) >= 2, "rerank probe returned fewer than two results"
    print(
        "ASSERT OK: multi-candidate search reported semantic=true and "
        f"reranked=true for {len(results)} results."
    )


async def _session(endpoint: str, token: str):
    from mcp import ClientSession  # lazy: keep --help importable without mcp installed
    from mcp.client.streamable_http import streamablehttp_client

    return streamablehttp_client(
        f"{endpoint}/mcp", headers={"Authorization": f"Bearer {token}"}
    ), ClientSession


async def _delete_memory(s, memory_id: str) -> None:
    txt = await _call(
        s,
        "DELETE_MEMORY",
        "delete_memory",
        {"memory_id": memory_id},
        retries=5,
        delay=2,
    )
    payload = _tool_payload(txt, "delete_memory")
    deleted_id = _memory_id(payload, "delete_memory")
    assert payload.get("status") == "deleted" and deleted_id == memory_id, (
        f"delete_memory did not delete exact memory id {memory_id!r}: {txt[:300]}"
    )


async def _run_search(
    s,
    *,
    marker: str | None = None,
    cleanup: bool = True,
) -> _SearchProbe:
    """Add and search one unique marker, cleaning the exact added id by default."""
    marker = marker or _new_marker()
    memory_id: str | None = None
    try:
        add_txt = await _call(
            s,
            "ADD_MEMORY",
            "add_memory",
            {"content": f"protocol self-test memory {marker}"},
        )
        add_payload = _tool_payload(add_txt, "add_memory")
        memory_id = _memory_id(add_payload, "add_memory")
        assert "dedup_warning" not in add_payload, (
            "add_memory returned a duplicate warning; unique probe was not saved"
        )
        search_txt = await _call(
            s,
            "SEARCH_MEMORY",
            "search_memory",
            {"query": marker},
        )
        return _SearchProbe(marker, memory_id, search_txt)
    except BaseException:
        if not cleanup and memory_id is not None:
            try:
                await _delete_memory(s, memory_id)
            except Exception as cleanup_exc:
                raise RuntimeError(
                    f"probe failed and cleanup failed for memory id {memory_id!r}"
                ) from cleanup_exc
        raise
    finally:
        if cleanup and memory_id is not None:
            await _delete_memory(s, memory_id)


async def _run_rerank(s) -> None:
    """Exercise semantic retrieval and reranking with three related memories."""
    marker = _new_marker("rerank")
    query = "enterprise multi-user team deployment backlog"
    contents = (
        f"{query} {marker}: tenant isolation and OAuth relay configuration.",
        f"{query} {marker}: Cloudflare container cold-start and cost controls "
        "for an MCP team.",
        f"{query} {marker}: per-sub credentials, D1 and Vectorize retrieval "
        "for an enterprise rollout.",
    )
    memory_ids: list[str] = []
    try:
        for index, content in enumerate(contents, start=1):
            add_txt = await _call(
                s,
                f"ADD_RERANK_{index}",
                "add_memory",
                {"content": content},
            )
            add_payload = _tool_payload(add_txt, "add_memory(rerank)")
            memory_id = _memory_id(add_payload, "add_memory(rerank)")
            assert add_payload.get("status") in {"saved", "created"}, add_payload
            memory_ids.append(memory_id)

        search_txt = await _call(
            s,
            "SEARCH_RERANK",
            "search_memory",
            {
                "query": query,
                "limit": 8,
            },
        )
        _assert_rerank_payload(search_txt, memory_ids)
    finally:
        for memory_id in reversed(memory_ids):
            await _delete_memory(s, memory_id)


def _token_file() -> Path:
    return Path(__file__).with_name(".wet_cf_token")


async def run_full(endpoint: str) -> None:
    token = get_token(endpoint, _creds())
    print("TOKEN OK len=", len(token), "sub=", _sub_of(token))
    transport, ClientSession = await _session(endpoint, token)
    async with transport as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        tools = await s.list_tools()
        print("TOOLS:", [t.name for t in tools.tools])
        await _call(s, "CONFIG_STATUS", "config", {"action": "status"})
        probe = await _run_search(s)
        _assert_search_resolved(probe.search_text, probe.marker, probe.memory_id)
        await _run_rerank(s)
    print("FULL FLOW PASS.")


async def run_backfill(endpoint: str, batch_size: int = 32) -> None:
    """Run the deployed request-scoped embedding backfill through MCP."""
    if not 1 <= batch_size <= 100:
        raise SystemExit("--batch-size must be between 1 and 100")
    token = get_token(endpoint, _creds())
    print("TOKEN OK len=", len(token), "sub=", _sub_of(token))
    transport, ClientSession = await _session(endpoint, token)
    async with transport as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        txt = await _call(
            s,
            "BACKFILL_EMBEDDINGS",
            "config",
            {"action": "backfill_embeddings", "batch_size": batch_size},
            retries=5,
            delay=2,
        )
    payload = _tool_payload(txt, "config(backfill_embeddings)")
    assert payload.get("status") == "completed", payload
    assert payload.get("failed") == 0, payload
    print("BACKFILL PASS:", _json.dumps(payload, sort_keys=True))


async def run_save_only(endpoint: str) -> None:
    token = get_token(endpoint, _creds())
    transport, ClientSession = await _session(endpoint, token)
    async with transport as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        await _call(s, "CONFIG_STATUS", "config", {"action": "status"})
    # Dump the EXACT token so --auth-only replays the SAME JWT sub (relay-login mints
    # a fresh random sub per /authorize).
    _token_file().write_text(token)
    print(
        "SAVE-ONLY OK: sub configured=",
        _sub_of(token),
        "(token dumped for --auth-only)",
    )


async def run_auth_only(endpoint: str) -> None:
    tok_path = _token_file()
    if not tok_path.exists():
        raise SystemExit("No dumped token -- run --save-only first.")
    token = tok_path.read_text().strip()
    print("AUTH-ONLY: replaying saved token for sub=", _sub_of(token))
    transport, ClientSession = await _session(endpoint, token)
    async with transport as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        probe = await _run_search(s)
        _assert_search_resolved(probe.search_text, probe.marker, probe.memory_id)
    print("AUTH-ONLY PASS: sub survived recreate (KV vault resolved, no re-save).")


async def run_two_sub_isolation(endpoint: str) -> None:
    token_a = get_token(endpoint, _creds())
    sub_a = _sub_of(token_a)
    token_b = get_token(endpoint, _creds())
    sub_b = _sub_of(token_b)
    print(f"sub A={sub_a}  sub B={sub_b}")
    if sub_a == sub_b:
        raise SystemExit(
            f"ISOLATION INCONCLUSIVE: both flows share sub {sub_a} (cannot test bleed)."
        )
    print("TWO-SUB: distinct bearer subjects acquired; testing marker isolation.")
    marker_a = _new_marker("isolation-a")
    marker_b = _new_marker("isolation-b")

    transport_a, ClientSession = await _session(endpoint, token_a)
    async with transport_a as (r_a, w_a, _), ClientSession(r_a, w_a) as s_a:
        await s_a.initialize()
        probe_a = await _run_search(s_a, marker=marker_a, cleanup=False)
        try:
            _assert_search_resolved(
                probe_a.search_text, probe_a.marker, probe_a.memory_id
            )

            transport_b, ClientSession = await _session(endpoint, token_b)
            async with transport_b as (r_b, w_b, _), ClientSession(r_b, w_b) as s_b:
                await s_b.initialize()
                search_a_from_b = await _call(
                    s_b,
                    "SEARCH_MEMORY_A_FROM_B",
                    "search_memory",
                    {"query": probe_a.marker},
                )
                _assert_search_absent(search_a_from_b, probe_a.marker)

                probe_b = await _run_search(s_b, marker=marker_b, cleanup=False)
                try:
                    _assert_search_resolved(
                        probe_b.search_text, probe_b.marker, probe_b.memory_id
                    )
                finally:
                    await _delete_memory(s_b, probe_b.memory_id)
        finally:
            await _delete_memory(s_a, probe_a.memory_id)
    print(
        "TWO-SUB ISOLATION OK: B could not find A marker and created/searched its own."
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="CF mnemo-mcp live OAuth full-flow self-test harness.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"Deployed mnemo endpoint (default: {DEFAULT_ENDPOINT})",
    )
    p.add_argument(
        "--cohere-cf-gateway",
        action="store_true",
        help=(
            "Use the existing CF_AIG_TOKEN as Cohere BYOK through CF_AIG_BASE; "
            "clears competing provider/model env values without logging secrets."
        ),
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--save-only",
        action="store_true",
        help="Configure one sub (empty form) + dump the token, then exit (recreate setup).",
    )
    mode.add_argument(
        "--auth-only",
        action="store_true",
        help="Replay the SAME token + search WITHOUT re-saving (recreate verify).",
    )
    mode.add_argument(
        "--backfill",
        action="store_true",
        help="Run the bounded request-scoped embedding backfill over deployed D1/Vectorize.",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Backfill batch size (1-100; default: 32).",
    )
    mode.add_argument(
        "--two-sub-isolation",
        action="store_true",
        help=(
            "Two distinct subs; B must not find A's marker before B creates "
            "and searches its own."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cohere_cf_gateway:
        _configure_cohere_cf_gateway()
    if args.save_only:
        asyncio.run(run_save_only(args.endpoint))
    elif args.auth_only:
        asyncio.run(run_auth_only(args.endpoint))
    elif args.backfill:
        asyncio.run(run_backfill(args.endpoint, args.batch_size))
    elif args.two_sub_isolation:
        asyncio.run(run_two_sub_isolation(args.endpoint))
    else:
        asyncio.run(run_full(args.endpoint))
    return 0


if __name__ == "__main__":
    sys.exit(main())
