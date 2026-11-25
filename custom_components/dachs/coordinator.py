"""Coordinator keeping the Dachs state fresh for all entities."""

from __future__ import annotations

from collections.abc import Callable
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
# cloud2 stays importable via the subpackage while its public exports
# are unpublished.
from senertec_dachs.cloud2 import CanIpDisplayFilter, Cloud2Client, UnitDetails
from senertec_dachs.cloud2.models import CanIpValue

from .const import (
    CONF_BASE_URL,
    CONF_CONNECTION,
    CONF_EMAIL,
    CONF_COOKIES,
    CONF_NATIVE_DATAPOINTS,
    CONF_PIN,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_PORTAL_ID,
    CONF_PORTAL_PASSWORD,
    CONNECTION_CLOUD,
    CONNECTION_CLOUD2,
    CONNECTION_GLT,
    CONNECTION_LOCAL,
    DEFAULT_GLT_PORT,
    DEFAULT_NATIVE_DATAPOINTS,
    DEFAULT_PORT,
    SCAN_INTERVAL_CLOUD_SECONDS,
    SCAN_INTERVAL_LOCAL_SECONDS,
)
from senertec_dachs import (
    AuthenticationError,
    Dachs,
    DachsError,
)

_LOGGER = logging.getLogger(__name__)

type DachsConfigEntry = ConfigEntry[DachsCoordinator]


class DachsCoordinator(DataUpdateCoordinator[Dachs]):
    """One coordinator per config entry; ``data`` is the serving Dachs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Build the device from the entry data; no I/O here."""
        mode = entry.data[CONF_CONNECTION]
        default_interval = (
            SCAN_INTERVAL_CLOUD_SECONDS
            if mode in (CONNECTION_CLOUD, CONNECTION_CLOUD2)
            else SCAN_INTERVAL_LOCAL_SECONDS
        )
        interval = int(entry.data.get(CONF_SCAN_INTERVAL, default_interval))
        super().__init__(
            hass,
            _LOGGER,
            name=entry.title,
            update_interval=timedelta(seconds=interval),
            config_entry=entry,
        )
        self.mode = mode
        self._device = _build_dachs(entry.data)
        # Native cloud2 datapoints: latest admitted value per stable
        # key, pushed to the sensor platform via the debounced data
        # update below. The library filter decides what a dashboard
        # shows (mirror/plain measurement/enum/transcript filtering);
        # hacs/ itself is only a consumer.
        self._display_filter = CanIpDisplayFilter()
        self.native_values: dict[str, CanIpValue] = {}
        # cloud2 daily history (portal chart rows) and the unit
        # identity snapshot; empty lists until the first fetch.
        self.history: dict[str, list] = {
            "electric": [],
            "heat": [],
            "run": [],
            "shutdown": [],
        }
        self.unit_details: UnitDetails | None = None
        self._native_push_unsub: Callable[[], None] | None = None
        self._listener_started = False
        self._native_platform_unsub: list[Callable[[], None]] = []

    @property
    def dachs(self) -> Dachs:
        """The device serving the last successful update."""
        return self.data

    @property
    def is_cloud(self) -> bool:
        """Whether a portal is involved (cloud or cloud2 mode)."""
        return self.mode in (CONNECTION_CLOUD, CONNECTION_CLOUD2)

    @property
    def supports_module_writes(self) -> bool:
        """Whether the MSR2 module-based write API is available.

        True for MSR2 local and the old Dachsportal. The GLT backend
        uses a watt setpoint instead of module counts, and cloud2 has
        no verified write path, so module-based controls only exist
        here.
        """
        return self.mode in (CONNECTION_LOCAL, CONNECTION_CLOUD)

    async def _async_update_data(self) -> Dachs:
        """Update via the configured backend."""
        try:
            await self._device.update()
        except AuthenticationError as error:
            raise ConfigEntryAuthFailed(str(error)) from error
        except DachsError as error:
            # Every library error (connection loss, timeouts, HTTP 5xx,
            # protocol garbage) must surface as UpdateFailed so the
            # coordinator keeps polling and recovers on its own; an
            # uncaught error here stops the polling loop entirely.
            raise UpdateFailed(f"Cannot reach the Dachs: {error}") from error
        self._maybe_start_native_listener()
        self._persist_session_cookies()
        client = getattr(self._device, "client", None)
        if isinstance(client, Cloud2Client):
            await self._async_fetch_cloud2_history(client)
        return self._device

    async def _async_fetch_cloud2_history(self, client: Cloud2Client) -> None:
        """Fetch the portal's per-day history for the daily cards.

        Best-effort per key: a failing chart endpoint keeps the
        previous value for that key and must not fail the coordinator
        cycle (a history outage must not blank the other daily cards
        either). ``unit_details`` is a sync snapshot of the already
        connected unit payload (no extra request).
        """
        self.unit_details = client.unit_details()
        for key, fetch, hours in (
            ("electric", client.daily_electric, 48),
            ("heat", client.daily_heat, 48),
            ("run", client.daily_run, 48),
            ("shutdown", client.shutdown_history, 25),
        ):
            try:
                self.history[key] = await fetch(hours=hours)
            except DachsError as error:
                _LOGGER.debug("Daily %s history unavailable: %s", key, error)

    @callback
    def _maybe_start_native_listener(self) -> None:
        """Start the cloud2 native datapoint listener, once, if enabled.

        The listener coexists with the facade polling above: the
        poll keeps the documented sensors current, the listener feeds
        the dynamic native ones via this coordinator's update cycle.
        """
        if self.mode != CONNECTION_CLOUD2 or self._listener_started:
            return
        if not self.config_entry.data.get(
            CONF_NATIVE_DATAPOINTS, DEFAULT_NATIVE_DATAPOINTS
        ):
            return
        client = getattr(self._device, "client", None)
        if not isinstance(client, Cloud2Client):
            return
        self._listener_started = True
        client.start_listener(self._async_on_native_value)

    @callback
    def _async_on_native_value(self, value: CanIpValue) -> None:
        """Store a value frame from the library listener.

        The library display filter guards every frame: junk tokens,
        free-form text, unit-less counters, mirror boards and values
        the electricity device never set are rejected here, so an
        entity is only ever created for an admitted value (lazy
        creation). Mirror boards likewise come out None and are
        silently ignored.
        """
        admitted = self._display_filter.admit(value)
        if admitted is None:
            return
        self.native_values[_native_key(admitted)] = admitted
        if self._native_push_unsub is None:
            self._native_push_unsub = async_call_later(
                self.hass, 1.0, self._async_push_native_update
            )

    async def _async_push_native_update(self, _now) -> None:
        """Debounced batch push of accumulated native values."""
        self._native_push_unsub = None
        self.async_set_updated_data(self._device)

    def attach_platform_listener(
        self, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a sensor-platform callback on the coordinator.

        The returned unsubscribe removes it; the platform never unbinds
        by itself — after unload the coordinator shutdown calls the
        remaining removers (:meth:`shutdown`).
        """
        unsub = self.async_add_listener(listener)
        self._native_platform_unsub.append(unsub)
        return unsub

    def _persist_session_cookies(self) -> None:
        """Keep the latest portal session cookies in entry data (cloud2).

        The library transparently falls back to a full SAML login when
        the persisted cookies have gone stale, so this write is
        change-checked: storage is touched only when the session
        actually rotated.
        """
        client = getattr(self._device, "client", None)
        if self.mode != CONNECTION_CLOUD2 or not isinstance(client, Cloud2Client):
            return
        cookies = client.session_cookies()
        if not cookies or cookies == self.config_entry.data.get(CONF_COOKIES):
            return
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={**self.config_entry.data, CONF_COOKIES: cookies},
        )

    def _stop_native(self) -> None:
        """Tear down the native listener and its push timer."""
        if self._native_push_unsub is not None:
            self._native_push_unsub()
            self._native_push_unsub = None
        for unsub in self._native_platform_unsub:
            unsub()
        self._native_platform_unsub.clear()
        client = getattr(self._device, "client", None)
        if self._listener_started and isinstance(client, Cloud2Client):
            client.stop_listener()
        self._listener_started = False

    async def request_run(self) -> None:
        """One-shot run request via the MSR2 write API."""
        await self._device.request_run()

    async def request_power(self, modules: int) -> None:
        """External power demand via the MSR2 write API."""
        await self._device.request_power(modules)

    async def shutdown(self) -> None:
        """Close the device object this coordinator owns."""
        self._stop_native()
        await self._device.close()


def _native_key(value: CanIpValue) -> str:
    """Stable coordinator key: datapoint id plus array element index.

    The filter owns the mirror-board dedupe, so the key only has to
    separate the datapoints themselves — array elements share their
    id, the element index disambiguates them.
    """
    if "[" in value.code:
        index = value.code.partition("[")[2].partition("]")[0]
        if index:
            return f"{value.id}[{index}]"
    return value.id


def _build_dachs(entry_data: dict) -> Dachs:
    """Build the device from entry data."""
    mode = entry_data[CONF_CONNECTION]
    if mode == CONNECTION_CLOUD:
        return _build_cloud_dachs(entry_data)
    if mode == CONNECTION_CLOUD2:
        return _build_cloud2_dachs(entry_data)
    if mode == CONNECTION_GLT:
        pin = entry_data.get(CONF_PIN)
        return Dachs.glt(
            entry_data[CONF_HOST],
            port=entry_data.get(CONF_PORT, DEFAULT_GLT_PORT),
            pin=int(pin) if pin else None,
        )
    return Dachs(
        entry_data[CONF_HOST],
        port=entry_data.get(CONF_PORT, DEFAULT_PORT),
        username=entry_data.get(CONF_USERNAME, "glt"),
        password=entry_data.get(CONF_PASSWORD, ""),
    )


def _build_cloud_dachs(entry_data: dict) -> Dachs:
    """Build the Dachsportal device from entry data."""
    base_url = entry_data.get(CONF_BASE_URL)
    if base_url:
        return Dachs.cloud(
            entry_data[CONF_PORTAL_ID],
            entry_data[CONF_PORTAL_PASSWORD],
            base_url=base_url,
        )
    return Dachs.cloud(
        entry_data[CONF_PORTAL_ID],
        entry_data[CONF_PORTAL_PASSWORD],
    )


def _build_cloud2_dachs(entry_data: dict) -> Dachs:
    """Build the DachsConnect device from entry data.

    Persisted session cookies (from the config flow or a prior
    session) seed the client's cookie jar; stale ones transparently
    fall back to the full SAML login.
    """
    return Dachs.cloud2(
        entry_data[CONF_EMAIL],
        entry_data[CONF_PASSWORD],
        serial=entry_data.get(CONF_SERIAL),
        cookies=entry_data.get(CONF_COOKIES),
    )
