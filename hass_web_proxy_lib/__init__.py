"""HASS Web Proxy library."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from http import HTTPStatus
from ipaddress import ip_address
from logging import Logger, getLogger
from typing import TYPE_CHECKING, Any

import aiohttp
import aiohttp.typedefs
from aiohttp import hdrs, web
from aiohttp.web_exceptions import HTTPBadGateway
from homeassistant.components.http import KEY_AUTHENTICATED, HomeAssistantView
from homeassistant.util.ssl import get_default_context
from multidict import CIMultiDict

LOGGER: Logger = getLogger(__package__)

if TYPE_CHECKING:
    import ssl

    from aiohttp.typedefs import LooseHeaders


class HASSWebProxyLibError(Exception):
    """Exception to indicate a general Proxy error."""


class HASSWebProxyLibBadRequestError(HASSWebProxyLibError):
    """Exception to indicate a bad (400) request."""


class HASSWebProxyLibUnauthorizedRequestError(HASSWebProxyLibError):
    """Exception to indicate an unauthorized (401) request."""


class HASSWebProxyLibForbiddenRequestError(HASSWebProxyLibError):
    """Exception to indicate an forbidden (403) request."""


class HASSWebProxyLibNotFoundRequestError(HASSWebProxyLibError):
    """Exception to indicate something is not found (404)."""


class HASSWebProxyLibExpiredError(HASSWebProxyLibError):
    """Exception to indicate an expired (410) request."""


EXPECTION_TO_HTTP_STATUS: dict[type[HASSWebProxyLibError], HTTPStatus] = {
    HASSWebProxyLibBadRequestError: HTTPStatus.BAD_REQUEST,
    HASSWebProxyLibForbiddenRequestError: HTTPStatus.FORBIDDEN,
    HASSWebProxyLibNotFoundRequestError: HTTPStatus.NOT_FOUND,
    HASSWebProxyLibExpiredError: HTTPStatus.GONE,
    HASSWebProxyLibUnauthorizedRequestError: HTTPStatus.UNAUTHORIZED,
}

# These proxies are inspired by:
#  - https://github.com/home-assistant/supervisor/blob/main/supervisor/api/ingress.py
#  - https://github.com/blakeblackshear/frigate-hass-integration/blob/master/custom_components/frigate/views.py


@dataclass
class ProxiedURL:
    """A proxied URL."""

    url: str
    ssl_context: ssl.SSLContext | None = None

    # Convenience parameter to set additional parameters in the proxied URL. Can
    # also just set the parameters directly in url (above).
    query_params: aiohttp.typedefs.Query = None

    # Unauthenticated requests must be explicitly marked.
    allow_unauthenticated: bool = False

    # Headers to be added to the request to the proxied URL (by default most
    # headers on the inbound request will be passed to the outbound request).
    headers: LooseHeaders | None = None


class ProxyView(HomeAssistantView):
    """HomeAssistant view."""

    # In _get_proxied_url_or_handle_error(...) all requests will be rejected if
    # they are unauthorized, unless the library caller explicitly sets
    # `allow_unauthenticated` to true.
    requires_auth = False

    def __init__(
        self,
        websession: aiohttp.ClientSession,
    ) -> None:
        """Initialize the HASS Web Proxy view."""
        self._websession = websession

    async def get(
        self,
        request: web.Request,
        **kwargs: Any,
    ) -> web.Response | web.StreamResponse | web.WebSocketResponse:
        """Route data to service."""
        try:
            return await self._handle_request(request, **kwargs)
        except aiohttp.ClientError as err:
            LOGGER.warning("Reverse proxy error for %s: %s", request.rel_url, err)
        raise HTTPBadGateway

    def _get_proxied_url_or_handle_error(
        self,
        request: web.Request,
        **kwargs: Any,
    ) -> ProxiedURL | web.Response:
        """Get the proxied URL or handle error."""
        try:
            url = self._get_proxied_url(request, **kwargs)
        except HASSWebProxyLibError as err:
            return web.Response(
                status=EXPECTION_TO_HTTP_STATUS.get(type(err), HTTPStatus.BAD_REQUEST)
            )

        if not url or not url.url:
            return web.Response(status=HTTPStatus.NOT_FOUND)

        if not request[KEY_AUTHENTICATED] and not url.allow_unauthenticated:
            return web.Response(status=HTTPStatus.UNAUTHORIZED)

        return url

    def _get_proxied_url(self, request: web.Request, **kwargs: Any) -> ProxiedURL:
        """Get the relevant Proxied URL."""
        raise NotImplementedError  # pragma: no cover

    async def _handle_request(
        self,
        request: web.Request,
        **kwargs: Any,
    ) -> web.Response | web.StreamResponse:
        """Handle route for request."""
        url_or_response = self._get_proxied_url_or_handle_error(request, **kwargs)
        if isinstance(url_or_response, web.Response):
            return url_or_response

        data = await request.read()
        source_header = _init_header(request, url_or_response.headers)

        async with self._websession.request(
            request.method,
            url_or_response.url,
            headers=source_header,
            params=url_or_response.query_params,
            allow_redirects=False,
            data=data,
            ssl=url_or_response.ssl_context or get_default_context(),
        ) as result:
            headers = _response_header(result)

            # Stream response
            response = web.StreamResponse(status=result.status, headers=headers)
            response.content_type = result.content_type

            try:
                await response.prepare(request)
                async for data in result.content.iter_any():
                    await response.write(data)

            except (aiohttp.ClientError, aiohttp.ClientPayloadError) as err:
                LOGGER.debug("Stream error for %s: %s", request.rel_url, err)
            except ConnectionResetError:
                # Connection is reset/closed by peer.
                pass

            return response


class WebsocketProxyView(ProxyView):
    """A simple proxy for websockets."""

    async def _proxy_msgs(
        self,
        ws_in: aiohttp.ClientWebSocketResponse | web.WebSocketResponse,
        ws_out: aiohttp.ClientWebSocketResponse | web.WebSocketResponse,
    ) -> None:
        async for msg in ws_in:
            try:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await ws_out.send_str(msg.data)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await ws_out.send_bytes(msg.data)
                elif msg.type == aiohttp.WSMsgType.PING:
                    await ws_out.ping()
                elif msg.type == aiohttp.WSMsgType.PONG:
                    await ws_out.pong()
            except ConnectionResetError:
                return

    async def _handle_request(
        self,
        request: web.Request,
        **kwargs: Any,
    ) -> web.Response | web.StreamResponse:
        """Handle route for request."""
        url_or_response = self._get_proxied_url_or_handle_error(request, **kwargs)
        if isinstance(url_or_response, web.Response):
            return url_or_response

        req_protocols = []
        if hdrs.SEC_WEBSOCKET_PROTOCOL in request.headers:
            req_protocols = [
                str(proto.strip())
                for proto in request.headers[hdrs.SEC_WEBSOCKET_PROTOCOL].split(",")
            ]

        ws_to_user = web.WebSocketResponse(
            protocols=req_protocols, autoclose=False, autoping=False
        )
        await ws_to_user.prepare(request)

        source_header = _init_header(request, url_or_response.headers)

        async with self._websession.ws_connect(
            url_or_response.url,
            headers=source_header,
            params=url_or_response.query_params,
            protocols=req_protocols,
            autoclose=False,
            autoping=False,
            ssl=url_or_response.ssl_context or get_default_context(),
        ) as ws_to_target:
            await asyncio.wait(
                [
                    asyncio.create_task(self._proxy_msgs(ws_to_target, ws_to_user)),
                    asyncio.create_task(self._proxy_msgs(ws_to_user, ws_to_target)),
                ],
                return_when=asyncio.tasks.FIRST_COMPLETED,
            )
        return ws_to_user


NO_COPY_HEADERS = [
    hdrs.CONTENT_LENGTH,
    hdrs.CONTENT_ENCODING,
    hdrs.SEC_WEBSOCKET_EXTENSIONS,
    hdrs.SEC_WEBSOCKET_PROTOCOL,
    hdrs.SEC_WEBSOCKET_VERSION,
    hdrs.SEC_WEBSOCKET_KEY,
    hdrs.HOST,
    hdrs.AUTHORIZATION,
]


def _init_header(
    request: web.Request,
    additional_headers: LooseHeaders | None = None,
) -> CIMultiDict[str]:
    """Create initial header."""
    headers: CIMultiDict[str] = CIMultiDict(
        {
            **{k: v for (k, v) in request.headers.items() if k not in NO_COPY_HEADERS},
            **CIMultiDict(additional_headers or {}),
        }
    )

    # Set X-Forwarded-For
    forward_for = request.headers.get(hdrs.X_FORWARDED_FOR)

    if request.transport:
        connected_ip = ip_address(request.transport.get_extra_info("peername")[0])
        if forward_for:
            forward_for = f"{forward_for}, {connected_ip!s}"
        else:
            forward_for = f"{connected_ip!s}"
        headers[hdrs.X_FORWARDED_FOR] = forward_for

    # Set X-Forwarded-Host
    forward_host = request.headers.get(hdrs.X_FORWARDED_HOST)
    if not forward_host:
        forward_host = request.host
    headers[hdrs.X_FORWARDED_HOST] = forward_host

    # Set X-Forwarded-Proto
    forward_proto = request.headers.get(hdrs.X_FORWARDED_PROTO)
    if not forward_proto:
        forward_proto = request.url.scheme
    headers[hdrs.X_FORWARDED_PROTO] = forward_proto

    return headers


def _response_header(response: aiohttp.ClientResponse) -> dict[str, str]:
    """Create response header."""
    headers = {}

    for name, value in response.headers.items():
        if name in (
            hdrs.TRANSFER_ENCODING,
            # Removing Content-Length header for streaming responses
            #   prevents seeking from working for mp4 files
            # hdrs.CONTENT_LENGTH,
            hdrs.CONTENT_TYPE,
            hdrs.CONTENT_ENCODING,
            # Strips inbound CORS response headers since the aiohttp_cors
            # library will assert that they are not already present for CORS
            # requests.
            hdrs.ACCESS_CONTROL_ALLOW_ORIGIN,
            hdrs.ACCESS_CONTROL_ALLOW_CREDENTIALS,
            hdrs.ACCESS_CONTROL_EXPOSE_HEADERS,
        ):
            continue
        headers[name] = value

    return headers
