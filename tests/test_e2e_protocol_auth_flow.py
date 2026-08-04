from __future__ import annotations

import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from urllib.parse import parse_qs, quote

import httpx
import pytest

_HARNESS_SPEC = spec_from_file_location(
    "e2e_mcp_protocol_test", Path(__file__).with_name("e2e_mcp_protocol_test.py")
)
assert _HARNESS_SPEC and _HARNESS_SPEC.loader
harness = module_from_spec(_HARNESS_SPEC)
_HARNESS_SPEC.loader.exec_module(harness)


def _response(
    request: httpx.Request,
    status_code: int,
    *,
    headers: dict[str, str] | None = None,
    json: object | None = None,
    text: str | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers=headers,
        json=json,
        text=text,
        request=request,
    )


@pytest.mark.parametrize("password_env", ["MCP_RELAY_PASSWORD", "RELAY_PW"])
async def test_obtain_jwt_handles_relay_login_redirect(
    monkeypatch: pytest.MonkeyPatch, password_env: str
) -> None:
    monkeypatch.setattr(harness, "BASE_URL", "https://mnemo.test")
    monkeypatch.setenv(password_env, "test-relay-password")
    if password_env == "MCP_RELAY_PASSWORD":
        monkeypatch.delenv("RELAY_PW", raising=False)
    else:
        monkeypatch.delenv("MCP_RELAY_PASSWORD", raising=False)

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/authorize":
            if "mcp_relay_session=fixture-session" not in request.headers.get(
                "cookie", ""
            ):
                next_url = quote(str(request.url), safe="")
                return _response(
                    request,
                    302,
                    headers={"location": f"/login?next={next_url}"},
                )
            return _response(
                request,
                200,
                text='<script>fetch("/authorize?nonce=redirect-nonce")</script>',
            )

        if request.method == "POST" and request.url.path == "/login":
            form = parse_qs(request.content.decode())
            assert form["password"] == ["test-relay-password"]
            assert form["next"]
            next_url = form["next"][0]
            return _response(
                request,
                302,
                headers={
                    "location": next_url,
                    "set-cookie": "mcp_relay_session=fixture-session; Path=/",
                },
            )

        if request.method == "POST" and request.url.path == "/authorize":
            assert request.url.params["nonce"] == "redirect-nonce"
            assert json.loads(request.content) == {"JINA_AI_API_KEY": "fixture-key"}
            return _response(
                request,
                200,
                json={
                    "redirect_url": "http://localhost:9999/cb?code=redirect-code&state=state"
                },
            )

        if request.method == "POST" and request.url.path == "/token":
            body = parse_qs(request.content.decode())
            assert body["code"] == ["redirect-code"]
            return _response(request, 200, json={"access_token": "fixture-jwt"})

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    client_class = httpx.AsyncClient
    with monkeypatch.context() as ctx:
        ctx.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: client_class(transport=transport, **kwargs),
        )
        with pytest.MonkeyPatch.context() as config_patch:
            config_patch.setattr(
                "mcp_core.storage.config_file.read_config",
                lambda _server_name: {"JINA_AI_API_KEY": "fixture-key"},
            )
            assert await harness.obtain_jwt() == "fixture-jwt"

    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/authorize"),
        ("POST", "/login"),
        ("GET", "/authorize"),
        ("POST", "/authorize"),
        ("POST", "/token"),
    ]


async def test_obtain_jwt_preserves_direct_authorize_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(harness, "BASE_URL", "https://mnemo.test")
    monkeypatch.delenv("MCP_RELAY_PASSWORD", raising=False)
    monkeypatch.delenv("RELAY_PW", raising=False)

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/authorize":
            return _response(
                request,
                200,
                text='<script>fetch("/authorize?nonce=direct-nonce")</script>',
            )
        if request.method == "POST" and request.url.path == "/authorize":
            assert request.url.params["nonce"] == "direct-nonce"
            return _response(
                request,
                200,
                json={
                    "redirect_url": "http://localhost:9999/cb?code=direct-code&state=state"
                },
            )
        if request.method == "POST" and request.url.path == "/token":
            body = parse_qs(request.content.decode())
            assert body["code"] == ["direct-code"]
            return _response(request, 200, json={"access_token": "fixture-jwt"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    client_class = httpx.AsyncClient
    with monkeypatch.context() as ctx:
        ctx.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: client_class(transport=transport, **kwargs),
        )
        with pytest.MonkeyPatch.context() as config_patch:
            config_patch.setattr(
                "mcp_core.storage.config_file.read_config",
                lambda _server_name: {"JINA_AI_API_KEY": "fixture-key"},
            )
            assert await harness.obtain_jwt() == "fixture-jwt"

    assert [request.url.path for request in requests] == [
        "/authorize",
        "/authorize",
        "/token",
    ]
