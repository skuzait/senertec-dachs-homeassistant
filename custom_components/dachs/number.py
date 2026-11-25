"""Number entities for the SenerTec Dachs integration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
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
    """Add the Dachs number entities for this config entry."""
    coordinator = entry.runtime_data
    if coordinator.mode not in (CONNECTION_LOCAL, CONNECTION_CLOUD):
        # The MSR2 module-based write API does not exist on the GLT
        # (watt setpoint) and cloud2 (unverified) backends.
        return
    async_add_entities([DachsPowerDemandNumber(coordinator)])


class DachsPowerDemandNumber(DachsEntity, NumberEntity):
    """External power demand in modules (0-10).

    Setting a value sends the demand; it is valid for ten minutes, so
    automations wanting sustained demand must renew it. The shown value
    mirrors the device's current requested-module count.
    """

    _attr_icon = "mdi:flash"
    _attr_translation_key = "power_demand"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 10
    _attr_native_step = 1

    def __init__(self, coordinator: DachsCoordinator) -> None:
        """Initialize the power-demand number."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_power_demand"

    @property
    def native_value(self) -> float | None:
        """The device's current external requested-module count."""
        data = self.coordinator.data
        return data.requested_modules if data is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Send the demand; 0 clears the external request."""
        await self.coordinator.request_power(int(value))
