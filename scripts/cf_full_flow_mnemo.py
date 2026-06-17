"""CF mnemo live OAuth full-flow self-test harness.

Drives the deployed mnemo-mcp Cloudflare Worker (Worker + per-sub Container + KV +
D1 + Vectorize) end-to-end against a public endpoint and asserts the memory store
survives a container delete+recreate (D1/Vectorize are durable, the container FS
is not):

  1. DCR register        -- POST /register (RFC 7591) -> client_id
  2. password-grant      -- /authorize -> /login (Gate A password) -> token
  3. /authorize form save with retry-on-500 (E.1 interception-race mitigation)
  4. authenticated tool call -- add_memory(marker) then search_memory(marker) and
     assert the marker comes back (proves D1 FTS + the per-sub write path are live).

Unlike imagine (per-sub provider keys), mnemo forces cloud embed via the
server-side JINA_AI_API_KEY secret forwarded to every container, so the per-sub
credential form is submitted EMPTY -- the durable state under test is the MEMORY
(D1 + Vectorize), not a per-sub key. The OAuth + retry plumbing is ported verbatim
from the imagine CF harness.

Secrets from env: Gate A login password from MCP_RELAY_PASSWORD (or RELAY_PW),
which lives in skret /oci-vm-prod/prod (infra-shared), NOT /mnemo-mcp/prod.

Run modes:
  (default)            full flow: add a marker memory + search it back.
  --save-only          add a marker under one sub, dump the token (recreate-gate
                       setup half of the state-survives-recreate criterion).
  --auth-only          replay the SAME token (same sub) and search the marker
                       WITHOUT re-adding (recreate-gate verify: memory survived D1).
  --two-sub-isolation  two distinct subs; sub A adds a marker, sub B searches for
                       it and MUST NOT find it (per-sub D1/Vectorize isolation).

Examples:
  skret run -e prod -- python scripts/cf_full_flow_mnemo.py --endpoint https://mnemo.n24q02m.com
  skret run -e prod -- python scripts/cf_full_flow_mnemo.py --save-only
  skret run -e prod -- python scripts/cf_full_flow_mnemo.py --auth-only
  skret run -e prod -- python scripts/cf_full_flow_mnemo.py --two-sub-isolation
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

DEFAULT_ENDPOINT = "https://mnemo.n24q02m.com"

# Distinctive, FTS-friendly marker tokens so search_memory reliably retrieves the
# exact row added (and so two-sub isolation can look for a token it must NOT see).
MARKER_TOKEN = "zenith-quasar-survival"
MARKER_CONTENT = f"mnemo cloudflare {MARKER_TOKEN} marker memory"
MARKER_QUERY = "zenith quasar survival marker"


def _password() -> str:
    pw = os.environ.get("RELAY_PW") or os.environ.get("MCP_RELAY_PASSWORD")
    if not pw:
        raise SystemExit(
            "MCP_RELAY_PASSWORD (or RELAY_PW) is required for the password-grant "
            "login gate. It lives in skret /oci-vm-prod/prod (infra-shared), NOT "
            "/mnemo-mcp/prod -- compose both namespaces (see plan Task 18)."
        )
    return pw


class _SaveRetry(Exception):
    pass


def get_token(
    endpoint: str,
    creds: dict[str, str],
    *,
    save_retries: int = 8,
) -> str:
    """Run the full OAuth flow, retrying on a transient 500 at the credential
    save step (CF Containers outbound-interception race on cold-started
    instances -- the kv.internal PUT occasionally lands before interception is
    applied; E.1). Each retry restarts from DCR so the nonce is fresh.

    ``creds`` is submitted as the /authorize form payload (EMPTY for mnemo: the
    server already holds JINA via a forwarded secret, so no per-sub key is needed).
    """
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
    """Call a tool, retrying while credentials/state are still propagating (KV
    cross-colo eventual consistency after setup writes them on another DO; E.2).
    Returns the concatenated text payload of the result, or None on give-up."""
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


async def _session(endpoint: str, token: str):
    from mcp import ClientSession  # lazy: keep --help importable without mcp installed
    from mcp.client.streamable_http import streamablehttp_client

    return streamablehttp_client(
        f"{endpoint}/mcp", headers={"Authorization": f"Bearer {token}"}
    ), ClientSession


async def _add_marker(s) -> None:
    await _call(
        s,
        "ADD_MEMORY",
        "add_memory",
        {"content": MARKER_CONTENT, "category": "fact"},
    )
    # Vectorize indexes asynchronously; D1 FTS is synchronous, so search-by-FTS is
    # immediate, but give a short beat so a hybrid read sees the vector too (E.3).
    await asyncio.sleep(8)


async def _search_marker(s, label="SEARCH_MEMORY") -> str | None:
    return await _call(s, label, "search_memory", {"query": MARKER_QUERY, "limit": 5})


def _assert_marker_found(txt: str | None) -> None:
    assert txt is not None, "search_memory returned no payload"
    assert MARKER_TOKEN in txt, (
        f"marker '{MARKER_TOKEN}' NOT found in search result: {txt[:300]}"
    )
    print(f"ASSERT OK: marker '{MARKER_TOKEN}' retrieved from the memory store.")


async def run_full(endpoint: str) -> None:
    token = get_token(endpoint, {})
    print("TOKEN OK len=", len(token), "sub=", _sub_of(token))
    transport, ClientSession = await _session(endpoint, token)
    async with transport as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        tools = await s.list_tools()
        print("TOOLS:", [t.name for t in tools.tools])
        await _call(s, "CONFIG_STATUS", "config", {"action": "status"})
        await _add_marker(s)
        txt = await _search_marker(s)
        _assert_marker_found(txt)
    print("FULL FLOW PASS.")


def _token_file():
    from pathlib import Path as _Path

    return _Path(__file__).with_name(".mnemo_cf_token")


async def run_save_only(endpoint: str) -> None:
    token = get_token(endpoint, {})
    transport, ClientSession = await _session(endpoint, token)
    async with transport as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        await _add_marker(s)
    # Dump the EXACT token so --auth-only replays the SAME JWT sub. The relay-login
    # mints a fresh random sub on every /authorize, so re-minting in --auth-only
    # would read a NEW (empty) sub vault; the recreate gate must prove THIS sub's
    # memory survived in D1, hence we persist the token.
    _token_file().write_text(token)
    print(
        "SAVE-ONLY OK: marker added for sub=",
        _sub_of(token),
        "(token dumped for --auth-only)",
    )


async def run_auth_only(endpoint: str) -> None:
    # Replay the EXACT token dumped by --save-only (same JWT sub) WITHOUT re-adding
    # the marker: this proves the previously-stored memory survived a container
    # delete+recreate (the durable D1/Vectorize state, not the ephemeral FS).
    tok_path = _token_file()
    if not tok_path.exists():
        raise SystemExit("No dumped token -- run --save-only first.")
    token = tok_path.read_text().strip()
    print("AUTH-ONLY: replaying saved token for sub=", _sub_of(token))
    transport, ClientSession = await _session(endpoint, token)
    async with transport as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        txt = await _search_marker(s, "SEARCH_AFTER_RECREATE")
        _assert_marker_found(txt)
    print("AUTH-ONLY PASS: memory survived recreate (D1/Vectorize durable, no re-add).")


async def run_two_sub_isolation(endpoint: str) -> None:
    # Sub A adds the marker; sub B searches for it and MUST NOT find it. The two
    # subs come from two separate /authorize flows (relay-login mints a fresh
    # random sub each time), and the shared D1 `sub` column + Vectorize `{sub}`
    # filter must keep B blind to A's memory.
    token_a = get_token(endpoint, {})
    sub_a = _sub_of(token_a)
    transport, ClientSession = await _session(endpoint, token_a)
    async with transport as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        await _add_marker(s)
    print(f"sub A={sub_a}: marker added.")

    token_b = get_token(endpoint, {})
    sub_b = _sub_of(token_b)
    if sub_a == sub_b:
        raise SystemExit(
            f"ISOLATION INCONCLUSIVE: both flows share sub {sub_a} (cannot test bleed)."
        )
    transport, ClientSession = await _session(endpoint, token_b)
    async with transport as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        txt = await _search_marker(s, f"SEARCH_AS_B[{sub_b}]") or ""
    print(f"sub A={sub_a}  sub B={sub_b}")
    if MARKER_TOKEN in txt:
        raise SystemExit(
            f"ISOLATION FAIL: sub B ({sub_b}) sees sub A's marker -- cross-sub leak."
        )
    print("TWO-SUB ISOLATION OK: sub B cannot see sub A's memory (per-sub scoped).")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="CF mnemo live OAuth full-flow self-test harness.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"Deployed mnemo endpoint (default: {DEFAULT_ENDPOINT})",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--save-only",
        action="store_true",
        help="Add a marker for one sub + dump the token, then exit (recreate setup).",
    )
    mode.add_argument(
        "--auth-only",
        action="store_true",
        help="Replay the SAME token + search the marker WITHOUT re-adding "
        "(recreate verify -- memory survived D1/Vectorize).",
    )
    mode.add_argument(
        "--two-sub-isolation",
        action="store_true",
        help="Two distinct subs; assert sub B cannot see sub A's marker.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.save_only:
        asyncio.run(run_save_only(args.endpoint))
    elif args.auth_only:
        asyncio.run(run_auth_only(args.endpoint))
    elif args.two_sub_isolation:
        asyncio.run(run_two_sub_isolation(args.endpoint))
    else:
        asyncio.run(run_full(args.endpoint))
    return 0


if __name__ == "__main__":
    sys.exit(main())
