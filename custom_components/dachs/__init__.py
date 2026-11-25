"""The SenerTec Dachs integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import DachsConfigEntry, DachsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: DachsConfigEntry
) -> bool:
    """Set up the Dachs integration from a config entry.

    Non-blocking: identity (serial/name) is known from the flow-time
    entry data, so setup finishes at once and the first data refresh
    runs in the background; entities appear with the device and fill
    their states when that refresh lands.
    """
    coordinator = DachsCoordinator(hass, entry)
    entry.runtime_data = coordinator
    entry.async_create_background_task(
        hass,
        coordinator.async_refresh(),
        name=f"dachs-first-refresh-{entry.entry_id}",
        eager_start=True,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: DachsConfigEntry
) -> bool:
    """Unload a Dachs config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.shutdown()
    return unload_ok
