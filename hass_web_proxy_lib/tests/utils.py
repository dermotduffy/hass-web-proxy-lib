"""Test utilities for hass_web_proxy_lib."""

from collections.abc import Generator
from typing import Any, Self, cast
from unittest.mock import patch

import aiohttp
import pytest
from aiohttp import web
from homeassistant.components.http import CONF_TRUSTED_PROXIES, CONF_USE_X_FORWARDED_FOR
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.plugins import (
    enable_custom_integrations,  # noqa: F401  # noqa: F401
)
from yarl import URL

from hass_web_proxy_lib import ProxiedURL, ProxyView

TEST_PROXY_URL = "/api/test_proxy"
TEST_PROXY_NAME = "api:test_proxy"


# This fixture is eused to prevent HomeAssistant from attempting to create and
# dismiss persistent notifications. These calls would fail without this fixture
# since the persistent_notification integration is never loaded during a test.
@pytest.fixture(name="skip_notifications")
def skip_notifications_fixture() -> Generator:
    """Skip notification calls."""
    with (
        patch("homeassistant.components.persistent_notification.async_create"),
        patch("homeassistant.components.persistent_notification.async_dismiss"),
    ):
        yield


@pytest.fixture(name="setup_http")
async def setup_http(hass: Any) -> None:
    """Configure http to allow a proxy."""
    # Configure http component to allow proxy before any other component can
    # depend on, and load, http.
    await async_setup_component(
        hass,
        "http",
        {
            "http": {
                CONF_USE_X_FORWARDED_FOR: True,
                CONF_TRUSTED_PROXIES: ["127.0.0.1"],
            }
        },
    )


@pytest.fixture(autouse=True)
def hass_web_proxy_fixture(
    socket_enabled: Any,
    skip_notifications: Any,
) -> None:
    """Automatically use an ordered combination of fixtures."""


class ClientErrorStreamResponse(web.StreamResponse):
    """StreamResponse for testing purposes that raises a ClientError."""

    async def write(self, _data: bytes) -> None:
        """Write data."""
        raise aiohttp.ClientError


class ConnectionResetStreamResponse(web.StreamResponse):
    """StreamResponse for testing purposes that raises a ConnectionResetError."""

    async def write(self, _data: bytes) -> None:
        """Write data."""
        raise ConnectionResetError


class FakeAsyncContextManager:
    """Fake AsyncContextManager for testing purposes."""

    async def __aenter__(self) -> Self:
        """Context manager enter."""
        return self

    async def __aexit__(self, *args: object, **kwargs: Any) -> None:
        """Context manager exit."""


@callback
async def register_test_view(  # noqa: PLR0913
    hass: HomeAssistant,
    proxied_url: ProxiedURL | None = None,
    exception: type[Exception] | None = None,
    kind: type[ProxyView] | None = None,
    register_url: str = TEST_PROXY_URL,
    register_name: str = TEST_PROXY_NAME,
) -> None:
    """Register the test proxy view."""

    # mypy doesn't handle variable superclasses correctly:
    # See: https://github.com/python/mypy/issues/14458
    class TestProxyView(kind or ProxyView):  # type: ignore[misc]
        """Test ProxyView."""

        url = register_url
        name = register_name

        def _get_proxied_url(self, _request: web.Request, **_kwargs: Any) -> ProxiedURL:
            """Get the relevant Proxied URL."""
            if exception:
                raise exception

            assert proxied_url
            return proxied_url

    session = async_get_clientsession(hass)
    hass.http.register_view(TestProxyView(session))


def _get_response_data(
    request: web.Request, **kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Get the response data for a given request."""
    return {
        "headers": dict(request.headers),
        "url": str(request.url),
        **kwargs,
    }


async def response_handler(request: web.Request) -> web.Response:
    """Return simple request data."""
    # Echo the request details back as the data.
    return web.json_response(
        status=200,
        data=_get_response_data(request),
    )


async def ws_response_handler(request: web.Request) -> web.WebSocketResponse:
    """Return simple request data."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # First send the request data back.
    await ws.send_json(_get_response_data(request))

    # Then echo back whatever is received.
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            await ws.send_str(msg.data)
        elif msg.type == aiohttp.WSMsgType.BINARY:
            await ws.send_bytes(msg.data)
    return ws


@pytest.fixture
async def local_server(
    setup_http: Any, hass: HomeAssistant, aiohttp_server: Any
) -> URL:
    """Local test server fixture."""
    app = web.Application()
    app.add_routes(
        [
            web.get("/", response_handler),
            web.get("/ws", ws_response_handler),
        ]
    )
    return cast(URL, (await aiohttp_server(app)).make_url("/"))
