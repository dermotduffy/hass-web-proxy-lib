"""Test the hass web proxy lib."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import aiohttp
import pytest
from aiohttp import hdrs

import hass_web_proxy_lib
from hass_web_proxy_lib import (
    HASSWebProxyLibBadRequestError,
    HASSWebProxyLibExpiredError,
    HASSWebProxyLibForbiddenRequestError,
    HASSWebProxyLibNotFoundRequestError,
    ProxiedURL,
    WebsocketProxyView,
)

from .utils import (
    TEST_PROXY_URL,
    ClientErrorStreamResponse,
    ConnectionResetStreamResponse,
    FakeAsyncContextManager,
    register_test_view,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def test_proxy_view_http_success(
    hass: HomeAssistant,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test that a valid URL proxies successfully."""
    await register_test_view(hass, proxied_url=ProxiedURL(url=local_server))

    authenticated_hass_client = await hass_client()
    resp = await authenticated_hass_client.get(TEST_PROXY_URL)
    assert resp.status == HTTPStatus.OK


async def test_proxy_view_http_success_header_verify(
    hass: HomeAssistant,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test that a valid URL proxies successfully."""
    await register_test_view(hass, proxied_url=ProxiedURL(url=local_server))

    authenticated_hass_client = await hass_client()
    source_headers = {
        hdrs.HOST: "example.com",
        hdrs.X_FORWARDED_FOR: "192.168.0.1",
        "my-header": "my-value",
    }
    resp = await authenticated_hass_client.get(TEST_PROXY_URL, headers=source_headers)
    assert resp.status == HTTPStatus.OK

    headers = (await resp.json())["headers"]
    assert headers["my-header"] == "my-value"
    assert headers[hdrs.X_FORWARDED_FOR] == "192.168.0.1, 127.0.0.1"
    assert headers[hdrs.X_FORWARDED_HOST] == "example.com"
    assert headers[hdrs.X_FORWARDED_PROTO] == "http"


@pytest.mark.usefixtures("local_server")
async def test_proxy_view_http_not_found(
    hass: HomeAssistant,
    hass_client: Any,
) -> None:
    """Test that a missing URL causes NOT_FOUND."""
    await register_test_view(hass, exception=HASSWebProxyLibNotFoundRequestError)

    authenticated_hass_client = await hass_client()
    resp = await authenticated_hass_client.get(TEST_PROXY_URL)
    assert resp.status == HTTPStatus.NOT_FOUND


@pytest.mark.usefixtures("local_server")
async def test_proxy_view_http_forbidden(
    hass: HomeAssistant,
    hass_client: Any,
) -> None:
    """Test that a forbidden URL causes FORBIDDEN."""
    await register_test_view(hass, exception=HASSWebProxyLibForbiddenRequestError)

    authenticated_hass_client = await hass_client()
    resp = await authenticated_hass_client.get(TEST_PROXY_URL)
    assert resp.status == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures("local_server")
async def test_proxy_view_http_gone(
    hass: HomeAssistant,
    hass_client: Any,
) -> None:
    """Test that an old URL causes GONE."""
    await register_test_view(hass, exception=HASSWebProxyLibExpiredError)

    authenticated_hass_client = await hass_client()
    resp = await authenticated_hass_client.get(TEST_PROXY_URL)
    assert resp.status == HTTPStatus.GONE


@pytest.mark.usefixtures("local_server")
async def test_proxy_view_http_bad_request(
    hass: HomeAssistant,
    hass_client: Any,
) -> None:
    """Test that an bad request causes BAD_REQUEST."""
    await register_test_view(hass, exception=HASSWebProxyLibBadRequestError)

    authenticated_hass_client = await hass_client()
    resp = await authenticated_hass_client.get(TEST_PROXY_URL)
    assert resp.status == HTTPStatus.BAD_REQUEST


@pytest.mark.usefixtures("local_server")
async def test_proxy_view_empty_proxied_url(
    hass: HomeAssistant,
    hass_client: Any,
) -> None:
    """Test that an empty proxied URL causes NOT_FOUND."""
    await register_test_view(hass, proxied_url=ProxiedURL(""))

    authenticated_hass_client = await hass_client()
    resp = await authenticated_hass_client.get(TEST_PROXY_URL)
    assert resp.status == HTTPStatus.NOT_FOUND


async def test_proxy_view_aiohttp_write_error(
    caplog: Any,
    hass: HomeAssistant,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test that an aiohttp error is handled."""
    await register_test_view(hass, proxied_url=ProxiedURL(url=local_server))

    authenticated_hass_client = await hass_client()

    with patch(
        "hass_web_proxy_lib.web.StreamResponse",
        new=ClientErrorStreamResponse,
    ):
        await authenticated_hass_client.get(TEST_PROXY_URL)
        assert "Stream error" in caplog.text


async def test_proxy_view_aiohttp_connection_reset_error(
    caplog: Any,
    hass: HomeAssistant,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test that an aiohttp connection reset is handled."""
    await register_test_view(hass, proxied_url=ProxiedURL(url=local_server))

    authenticated_hass_client = await hass_client()

    with patch(
        "hass_web_proxy_lib.web.StreamResponse",
        new=ConnectionResetStreamResponse,
    ):
        await authenticated_hass_client.get(TEST_PROXY_URL)
        assert "Stream error" not in caplog.text


async def test_proxy_view_aiohttp_read_error(
    hass: HomeAssistant,
    caplog: Any,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test snapshot request with a read error."""
    await register_test_view(hass, proxied_url=ProxiedURL(url=local_server))

    authenticated_hass_client = await hass_client()

    mock_request = MagicMock(FakeAsyncContextManager())
    mock_request.side_effect = aiohttp.ClientError

    with patch.object(
        hass.helpers.aiohttp_client.async_get_clientsession(),
        "request",
        new=mock_request,
    ):
        await authenticated_hass_client.get(TEST_PROXY_URL)
        assert "Reverse proxy error" in caplog.text


async def test_proxy_view_unauthorized(
    hass: HomeAssistant,
    local_server: Any,
    hass_client_no_auth: Any,
) -> None:
    """Test unauthorized requests are rejected."""
    await register_test_view(hass, proxied_url=ProxiedURL(url=local_server))

    unauthenticated_hass_client = await hass_client_no_auth()

    resp = await unauthenticated_hass_client.get(TEST_PROXY_URL)
    assert resp.status == HTTPStatus.UNAUTHORIZED


async def test_proxy_view_unauthorized_allowed(
    hass: HomeAssistant,
    local_server: Any,
    hass_client_no_auth: Any,
) -> None:
    """Test unauthorized requests are rejected."""
    await register_test_view(
        hass,
        proxied_url=ProxiedURL(url=local_server, allow_unauthenticated=True),
    )

    unauthenticated_hass_client = await hass_client_no_auth()

    resp = await unauthenticated_hass_client.get(TEST_PROXY_URL)
    assert resp.status == HTTPStatus.OK


async def test_proxy_view_unauthorized_not_allowed(
    hass: HomeAssistant,
    local_server: Any,
    hass_client_no_auth: Any,
) -> None:
    """Test unauthorized requests are rejected."""
    await register_test_view(
        hass,
        proxied_url=ProxiedURL(url=local_server, allow_unauthenticated=False),
    )

    unauthenticated_hass_client = await hass_client_no_auth()

    resp = await unauthenticated_hass_client.get(TEST_PROXY_URL)
    assert resp.status == HTTPStatus.UNAUTHORIZED


async def test_headers(
    hass: HomeAssistant,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test proxy headers are added and respected."""
    await register_test_view(hass, proxied_url=ProxiedURL(url=local_server))

    authenticated_hass_client = await hass_client()

    resp = await authenticated_hass_client.get(
        TEST_PROXY_URL,
        headers={hdrs.CONTENT_ENCODING: "foo"},
    )
    assert resp.status == HTTPStatus.OK

    resp = await authenticated_hass_client.get(
        TEST_PROXY_URL,
        headers={hdrs.X_FORWARDED_FOR: "1.2.3.4"},
    )
    assert resp.status == HTTPStatus.OK


async def test_proxy_view_websocket_success(
    hass: Any,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test proxying websocket connection."""
    await register_test_view(
        hass, proxied_url=ProxiedURL(url=f"{local_server}ws"), kind=WebsocketProxyView
    )

    authenticated_hass_client = await hass_client()

    async with authenticated_hass_client.ws_connect(TEST_PROXY_URL) as ws:
        await ws.ping()

        request = await ws.receive_json()
        assert request["url"] == f"{local_server}ws"

        # Test sending text data.
        result = await asyncio.gather(
            ws.send_str("hello!"),
            ws.receive(),
        )
        assert result[1].type == aiohttp.WSMsgType.TEXT
        assert result[1].data == "hello!"

        # # Test sending binary data.
        result = await asyncio.gather(
            ws.send_bytes(b"\x00\x01"),
            ws.receive(),
        )

        assert result[1].type == aiohttp.WSMsgType.BINARY
        assert result[1].data == b"\x00\x01"


async def test_proxy_view_websocket_connection_reset(
    hass: Any,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test proxy websocket handles connection resets."""
    await register_test_view(
        hass, proxied_url=ProxiedURL(url=f"{local_server}ws"), kind=WebsocketProxyView
    )

    # Tricky: This test is intended to test a ConnectionResetError to the
    # backend server, which is the _second_ call to send*. The first call (from
    # this test) needs to succeed.
    real_send_str = hass_web_proxy_lib.aiohttp.web.WebSocketResponse.send_str
    called_once = False

    async def send_str(*args: Any, **kwargs: Any) -> None:
        nonlocal called_once
        if called_once:
            raise ConnectionResetError
        called_once = True
        return await real_send_str(*args, **kwargs)

    authenticated_hass_client = await hass_client()

    with patch(
        "hass_web_proxy_lib.aiohttp.ClientWebSocketResponse.send_str",
        new=send_str,
    ):
        async with authenticated_hass_client.ws_connect(TEST_PROXY_URL) as ws:
            await ws.send_str("data")


@pytest.mark.usefixtures("local_server")
async def test_proxy_view_websocket_not_found(
    hass: HomeAssistant,
    hass_client: Any,
) -> None:
    """Test that an invalid ProxiedURL for a websocket proxy is handled."""
    await register_test_view(
        hass, exception=HASSWebProxyLibNotFoundRequestError, kind=WebsocketProxyView
    )

    authenticated_hass_client = await hass_client()
    resp = await authenticated_hass_client.get(TEST_PROXY_URL)
    assert resp.status == HTTPStatus.NOT_FOUND


async def test_proxy_view_websocket_specify_protocol(
    hass: Any,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test websocket proxy handles the SEC_WEBSOCKET_PROTOCOL header."""
    await register_test_view(
        hass, proxied_url=ProxiedURL(url=f"{local_server}ws"), kind=WebsocketProxyView
    )

    authenticated_hass_client = await hass_client()

    async with authenticated_hass_client.ws_connect(
        TEST_PROXY_URL, headers={hdrs.SEC_WEBSOCKET_PROTOCOL: "foo,bar"}
    ) as ws:
        assert ws
        await ws.close()


async def test_proxy_view_http_query_parameters_set(
    hass: HomeAssistant,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test that query parameters are set on request."""
    await register_test_view(
        hass,
        proxied_url=ProxiedURL(
            url=f"{local_server}?a=1&b=2", query_params={"a": "2", "c": "3"}
        ),
    )

    authenticated_hass_client = await hass_client()
    resp = await authenticated_hass_client.get(TEST_PROXY_URL)
    assert resp.status == HTTPStatus.OK

    json = await resp.json()
    assert json["url"] == f"{local_server}?a=1&b=2&a=2&c=3"


async def test_proxy_view_websocket_query_parameters_set(
    hass: HomeAssistant,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test that query parameters are set on a websocket request."""
    await register_test_view(
        hass,
        proxied_url=ProxiedURL(
            url=f"{local_server}ws?a=1&b=2", query_params={"a": "2", "c": "3"}
        ),
        kind=WebsocketProxyView,
    )

    authenticated_hass_client = await hass_client()

    async with authenticated_hass_client.ws_connect(TEST_PROXY_URL) as ws:
        request = await ws.receive_json()
        assert request["url"] == f"{local_server}ws?a=1&b=2&a=2&c=3"


async def test_proxy_view_http_headers_set(
    hass: HomeAssistant,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test that headers are set on a request."""
    await register_test_view(
        hass,
        proxied_url=ProxiedURL(
            url=str(local_server),
            headers={"foo": "bar", "X-Forwarded-For": "ROGUE_VALUE"},
        ),
    )

    authenticated_hass_client = await hass_client()
    resp = await authenticated_hass_client.get(TEST_PROXY_URL)
    assert resp.status == HTTPStatus.OK

    json = await resp.json()
    assert json["headers"]["foo"] == "bar"

    # Certain headers cannot be overridden.
    assert json["headers"]["X-Forwarded-For"] != "ROGUE_VALUE"


async def test_proxy_view_websocket_headers_set(
    hass: HomeAssistant,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test that headers are set on a websocket request."""
    await register_test_view(
        hass,
        proxied_url=ProxiedURL(
            url=f"{local_server}ws?a=1&b=2",
            headers={"foo": "bar", "X-Forwarded-For": "ROGUE_VALUE"},
        ),
        kind=WebsocketProxyView,
    )

    authenticated_hass_client = await hass_client()

    async with authenticated_hass_client.ws_connect(TEST_PROXY_URL) as ws:
        request = await ws.receive_json()

        assert request["headers"]["foo"] == "bar"

        # Certain headers cannot be overridden.
        assert request["headers"]["X-Forwarded-For"] != "ROGUE_VALUE"
