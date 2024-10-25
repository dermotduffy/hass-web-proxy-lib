# `hass-web-proxy-lib`

A small [Home Assistant](https://www.home-assistant.io/) library to proxy
authenticated web traffic through Home Assistant. Used by the [Home Assistant
Web Proxy
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
must implement `_get_proxied_url(...)`.

### `WebsocketProxyView`

The class to inherit from for websocket proxying. Inheritors must implement
`_get_proxied_url(...)`.

### Errors

#### `HASSWebProxyLibBadRequestError`

Can be raised by `_get_proxied_url(...)` to indicate a bad request ([`400 Bad
Request`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400)).

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
