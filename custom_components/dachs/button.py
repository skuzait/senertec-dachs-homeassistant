"""Buttons for the SenerTec Dachs integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONNECTION_CLOUD, CONNECTION_LOCAL
from .coordinator import DachsConfigEntry, DachsCoordinator
from .entity import DachsEntity



async def async_setup_entry(
    hass: HomeAssistant,
    entry: DachsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the Dachs buttons for this config entry."""
    coordinator = entry.runtime_data
    if coordinator.mode not in (CONNECTION_LOCAL, CONNECTION_CLOUD):
        # The MSR2 module-based write API does not exist on the GLT
        # (watt setpoint) and cloud2 (unverified) backends.
        return
    async_add_entities([DachsRequestRunButton(coordinator)])


class DachsRequestRunButton(DachsEntity, ButtonEntity):
    """One-shot run request — the app's "Anfrage" button."""

    _attr_icon = "mdi:play"
    _attr_translation_key = "request_run"

    def __init__(self, coordinator: DachsCoordinator) -> None:
        """Initialize the run button."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_request_run"

    async def async_press(self) -> None:
        """Send the run request via the active backend."""
        await self.coordinator.request_run()
