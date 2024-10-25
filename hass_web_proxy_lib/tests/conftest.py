"""Global fixtures for HASS Web Proxy integration."""

pytest_plugins = [
    "pytest_homeassistant_custom_component",
    "hass_web_proxy_lib.tests.utils",
]
