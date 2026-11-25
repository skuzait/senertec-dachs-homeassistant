"""Constants for the SenerTec Dachs integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "dachs"
PLATFORMS: Final = ("binary_sensor", "button", "number", "sensor")

# Connection modes offered by the config flow.
CONNECTION_LOCAL: Final = "local"  # MSR2 GLT interface, HTTP
CONNECTION_GLT: Final = "glt"  # MSR3 / Gen2 GLT interface, Modbus TCP
CONNECTION_CLOUD: Final = "cloud"  # old Dachsportal (DachsApp backend)
CONNECTION_CLOUD2: Final = "cloud2"  # DachsConnect / DachsPortal2 — not published yet
CONNECTION_LOCAL_AUTO: Final = "local_auto"  # probe MSR2, then MSR3
CONNECTION_MODES: Final = (
    CONNECTION_LOCAL_AUTO,
    CONNECTION_LOCAL,
    CONNECTION_GLT,
    CONNECTION_CLOUD,
    # CONNECTION_CLOUD2,  # DachsConnect not reliable yet; re-enable when it ships.
)

# Config-entry keys (HA built-ins: host, port, username, password, email).
CONF_CONNECTION: Final = "connection"
CONF_BASE_URL: Final = "base_url"
CONF_EMAIL: Final = "email"
CONF_PIN: Final = "pin"
CONF_PORTAL_ID: Final = "portal_id"
CONF_PORTAL_PASSWORD: Final = "portal_password"
CONF_PRODUCT_NAME: Final = "product_name"
CONF_SCAN_INTERVAL: Final = "scan_interval"
# cloud2 only: show every native datapoint beside the documented facade ones.
# Off by default: the full unit exposes hundreds of mostly service-grade
# datapoints; the curated facade is what a dashboard wants. Opt in here.
CONF_NATIVE_DATAPOINTS: Final = "native_datapoints"
DEFAULT_NATIVE_DATAPOINTS: Final = False
# cloud2 only: persisted portal session cookies for fast logins.
CONF_COOKIES: Final = "session_cookies"
CONF_SERIAL: Final = "serial"
MIN_SCAN_INTERVAL_SECONDS: Final = 15

# MSR2 GLT interface defaults.
DEFAULT_PORT: Final = 8080
DEFAULT_USERNAME: Final = "glt"

# MSR3 GLT interface defaults.
DEFAULT_GLT_PORT: Final = 502

# Poll interval defaults: the local interfaces are cheap and live; the
# portals poll the device themselves, so faster asking is wasted.
SCAN_INTERVAL_LOCAL_SECONDS: Final = 30
SCAN_INTERVAL_CLOUD_SECONDS: Final = 120
MAX_SCAN_INTERVAL_SECONDS: Final = 86400
