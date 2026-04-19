"""E2E MCP protocol test — hit running mnemo-mcp HTTP server via StreamableHTTP + OAuth PKCE.

Flow:
1. Generate PKCE pair
2. GET /authorize -> parse HTML, extract nonce from inline JS.
3. POST /authorize?nonce=<nonce> with JSON body = existing credentials -> get auth_code
4. POST /token with code + code_verifier -> get JWT
5. Open MCP session with Bearer JWT, call each tool, print results

Adapted from wet-mcp/tests/e2e_mcp_protocol_test.py for mnemo-mcp.
Tools: memory, config, help.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import re
import secrets
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

BASE_URL = os.environ.get("MNEMO_BASE_URL", "http://127.0.0.1:0").rstrip("/")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


async def obtain_jwt() -> str:
    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)
    redirect_uri = "http://localhost:9999/cb"
    client_id = "e2e-test"

    async with httpx.AsyncClient(timeout=60) as http:
        resp = await http.get(
            f"{BASE_URL}/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        print(f"[1] GET /authorize -> {resp.status_code}")
        assert resp.status_code == 200, resp.text[:300]

        match = re.search(r"/authorize\?nonce=([A-Za-z0-9_\-]+)", resp.text)
        assert match, f"Nonce not found in HTML: {resp.text[:500]}"
        nonce = match.group(1)
        print(f"[1] nonce={nonce[:16]}...")

        from mcp_core.storage.config_file import read_config

        existing = read_config("mnemo-mcp") or {}
        print(f"[2] Re-submitting existing credentials: {list(existing.keys())}")

        resp = await http.post(
            f"{BASE_URL}/authorize",
            params={"nonce": nonce},
            json=existing,
        )
        print(f"[3] POST /authorize -> {resp.status_code}")
        assert resp.status_code == 200, resp.text[:500]
        body = resp.json()
        redirect_url = body["redirect_url"]
        code_match = re.search(r"[?&]code=([^&]+)", redirect_url)
        assert code_match, redirect_url
        auth_code = code_match.group(1)
        print(f"[3] auth_code={auth_code[:16]}...")

        resp = await http.post(
            f"{BASE_URL}/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
            },
        )
        print(f"[4] POST /token -> {resp.status_code}")
        assert resp.status_code == 200, resp.text[:500]
        tok = resp.json()
        jwt = tok.get("access_token")
        assert jwt, tok
        print(f"[4] JWT obtained: {jwt[:40]}...")
        return jwt


def _short(s: Any, n: int = 240) -> str:
    text = str(s)
    text = text.replace("\n", " ")
    if len(text) <= n:
        return text
    return text[:n] + "..."


async def call_tool(
    session: ClientSession, name: str, args: dict | None = None, timeout: float = 60.0
) -> dict:
    result: dict = {"tool": name, "args": args}
    try:
        resp = await asyncio.wait_for(
            session.call_tool(name, arguments=args or {}), timeout=timeout
        )
        parts = []
        for item in resp.content:
            t = getattr(item, "text", None)
            if t is not None:
                parts.append(t)
            else:
                parts.append(str(item))
        combined = "\n".join(parts)
        result["status"] = "OK" if not resp.isError else "ERROR"
        result["response"] = combined
        result["is_error"] = bool(resp.isError)
    except TimeoutError:
        result["status"] = "TIMEOUT"
        result["response"] = f"Tool call exceeded {timeout}s"
    except Exception as e:
        result["status"] = "EXCEPTION"
        result["response"] = f"{type(e).__name__}: {e}"
    return result


async def main() -> list[dict]:
    jwt = await obtain_jwt()

    headers = {"Authorization": f"Bearer {jwt}"}
    print(f"\n[MCP] Connecting to {BASE_URL}/mcp with Bearer auth...")

    async with streamablehttp_client(f"{BASE_URL}/mcp", headers=headers) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("[MCP] Initialized")

            tools_resp = await session.list_tools()
            names = [t.name for t in tools_resp.tools]
            print(f"[MCP] Tools available: {names}")

            # memory_id captured after add, used for update/delete
            shared: dict[str, str] = {}

            tests: list[tuple[str, dict, float]] = [
                ("help", {}, 30.0),
                ("help", {"topic": "memory"}, 30.0),
                ("help", {"topic": "config"}, 30.0),
                ("config", {"action": "status"}, 30.0),
                ("config", {"action": "setup_status"}, 30.0),
                # warmup may try to download ONNX model — keep timeout big, allow failure
                ("config", {"action": "warmup"}, 120.0),
                (
                    "memory",
                    {
                        "action": "add",
                        "content": "E2E test memory entry — Paris is the capital of France",
                        "category": "e2e_test",
                        "tags": ["e2e", "geography"],
                    },
                    60.0,
                ),
                (
                    "memory",
                    {"action": "search", "query": "capital of France", "limit": 3},
                    60.0,
                ),
                (
                    "memory",
                    {"action": "list", "category": "e2e_test", "limit": 5},
                    30.0,
                ),
                ("memory", {"action": "stats"}, 30.0),
            ]

            results = []
            for tool_name, args, timeout in tests:
                print(f"\n>>> Calling {tool_name}({args})")
                r = await call_tool(session, tool_name, args, timeout=timeout)
                results.append(r)
                print(f"    status={r['status']}")
                print(f"    response={_short(r['response'], 240)}")

                # Capture memory_id from add response to test delete afterwards
                if (
                    tool_name == "memory"
                    and args.get("action") == "add"
                    and r["status"] == "OK"
                ):
                    m = re.search(r'"id":\s*"([^"]+)"', r["response"])
                    if m:
                        shared["memory_id"] = m.group(1)
                        print(f"    captured memory_id={shared['memory_id']}")

            # Additional tests that depend on captured memory_id
            if shared.get("memory_id"):
                extra = [
                    (
                        "memory",
                        {"action": "delete", "memory_id": shared["memory_id"]},
                        30.0,
                    ),
                ]
                for tool_name, args, timeout in extra:
                    print(f"\n>>> Calling {tool_name}({args})")
                    r = await call_tool(session, tool_name, args, timeout=timeout)
                    results.append(r)
                    print(f"    status={r['status']}")
                    print(f"    response={_short(r['response'], 240)}")

            print("\n" + "=" * 60)
            print("SUMMARY")
            print("=" * 60)
            pass_count = 0
            for r in results:
                status = "PASS" if r["status"] == "OK" else "FAIL"
                if status == "PASS":
                    pass_count += 1
                print(f"[{status}] {r['tool']}({r['args']}) -> {r['status']}")
            print(f"\nTotal: {pass_count}/{len(results)} PASS")

            return results


if __name__ == "__main__":
    asyncio.run(main())
