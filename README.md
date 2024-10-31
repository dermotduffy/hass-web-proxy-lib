# `hass-web-proxy-lib`

A small [Home Assistant](https://www.home-assistant.io/) library to proxy web
traffic through Home Assistant. Used by the [Home Assistant Web Proxy
Integration](https://github.com/dermotduffy/hass-web-proxy-integration/) and any
other integration that needs to proxy traffic through Home Assistant.

This library is not itself an integration but rather can be used by integration
developers to offer proxying capabilities within their own integration.

## Usage

Use this library as part of your custom integration by declaring a new
`HomeAssistantView` that inherits from the `ProxyView` or `WebsocketProxyView`
class in this library. Callers must implement the `_get_proxied_url` method to
return a `ProxiedURL` object containing a destination URL for a given proxy
request, or raising an exception to indicate an error condition.

## Example Usage

Proxies a `GET` request from `https://$HA_INSTANCE/api/my_integration/proxy/`
through to whatever URL is specified in the `url` query string parameter of the
request.

```py
@callback
async def async_setup_entry(hass: HomeAssistant) -> None:
    """Set up the HASS web proxy entry."""
    session = async_get_clientsession(hass)
    hass.http.register_view(MyProxyView(hass, session))


class MyProxyView(ProxyView):
    """A proxy view for My Integration."""

    url = "/api/my_integration/proxy/"
    name = "api:my_integration:proxy"

    def _get_proxied_url(self, request: web.Request) -> ProxiedURL:
        """Get the URL to proxy."""
        if "url" not in request.query:
            raise HASSWebProxyLibNotFoundRequestError
        return ProxiedURL(url=urllib.parse.unquote(request.query["url"]))
```

See the
[`hass-web-proxy-integration`](https://github.com/dermotduffy/hass-web-proxy-integration/blob/main/custom_components/hass_web_proxy/proxy.py)
for a more complete example of usage of this library.

## Key Classes

### `ProxyView`

The main class to inherit from for simple `GET` request proxying. Inheritors
must implement `_get_proxied_url(...)` to return a `ProxiedURL` object.

### `WebsocketProxyView`

The class to inherit from for websocket proxying. Inheritors must implement
`_get_proxied_url(...)` to return a `ProxiedURL` object.

### ProxiedURL

A small dataclass returned by overridden `_get_proxied_url(...)` methods that describes how the library should proxy a given request.

| Field name              | Default | Description                                                                                                                                                                                                                |
| ----------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `url`                   |         | The destination URL a given request should be made to, e.g. `https://my-backend.my-domain.io`.                                                                                                                             |
| `ssl_context`           |         | An optional [`SSLContext`](https://docs.python.org/3/library/ssl.html#ssl.SSLContext) object that should be used for secure onward requests.                                                                               |
| `query_params`          |         | An optional dictionary of query parameters to set in the target URL. This is a convenience alternative to the caller simply adding the query string parameters onto the `url` parameter.                                   |
| `allow_unauthenticated` | `False` | When `False` or unset, unauthenticated HA traffic will be rejected with a [`401 Unauthorized`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401) status. When `True`, unauthenticated traffic will be allowed. |

### Errors

#### `HASSWebProxyLibBadRequestError`

Can be raised by `_get_proxied_url(...)` to indicate a bad request ([`400 Bad
Request`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400)).

#### `HASSWebProxyLibUnauthorizedRequestError`

Can be raised by `_get_proxied_url(...)` to indicate an unauthorized request
([`401
Unauthorized`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401)).

#### `HASSWebProxyLibForbiddenRequestError`

Can be raised by `_get_proxied_url(...)` to indicate a forbidden request ([`403
Forbidden`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403)).

#### `HASSWebProxyLibNotFoundRequestError`

Can be raised by `_get_proxied_url(...)` to indicate a request is not found request
([`404 Not
Found`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404)).

#### `HASSWebProxyLibExpiredError`

Can be raised by `_get_proxied_url(...)` to indicate an expired / permanently removed
resource is not available ([`410
Gone`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/410)).

## Testing

This library also contains a small [test utility and fixture
file](https://github.com/dermotduffy/hass-web-proxy-lib/blob/main/hass_web_proxy_lib/tests/utils.py)
that can be used to test proxying.

The `local_server` fixture will start a small `aiohttp` server that can be
"proxied to". The server listens to `/` and `/ws` for simple `GET` requests
and websockets respectively.

### `/`

The `/` handler will return a `json` object containing:

| Field name | Description                                   |
| ---------- | --------------------------------------------- |
| `headers`  | A dictionary of the request headers received. |
| `url`      | The full URL/querystring requested.           |

### `/ws`

The `/ws` handler will initially return a `json` object containing `headers` and
`url` (as in `/` above), and then will simply echo back text or binary data.

### Example Test Usage

```py
import pytest

# Add the HA and local_server fixtures.
pytest_plugins = [
    "pytest_homeassistant_custom_component",
    "hass_web_proxy_lib.tests.utils",
]

async def test_proxy_view_success(
    hass: HomeAssistant,
    local_server: Any,
    hass_client: Any,
) -> None:
    """Test that a valid URL proxies successfully."""
    authenticated_hass_client = await hass_client()
    resp = await authenticated_hass_client.get(
        f"/api/my_integration/proxy/?url={urllib.parse.quote_plus(local_server)}"
    )
    assert resp.status == HTTPStatus.OK
```
