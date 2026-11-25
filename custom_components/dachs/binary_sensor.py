"""Binary sensors for the SenerTec Dachs integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONNECTION_CLOUD2
from .coordinator import DachsConfigEntry, DachsCoordinator
from .entity import DachsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DachsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the Dachs binary sensors for this config entry."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        DachsRunningBinarySensor(coordinator),
        DachsMaintenanceBinarySensor(coordinator),
    ]
    if coordinator.is_cloud:
        # The portal can fail to reach the device; surface that honestly.
        entities.append(DachsOnlineBinarySensor(coordinator))
    if coordinator.mode == CONNECTION_CLOUD2:
        # The portal's own unit banner: active warnings of the unit.
        entities.append(DachsWarningBinarySensor(coordinator))
    async_add_entities(entities)


class DachsRunningBinarySensor(DachsEntity, BinarySensorEntity):
    """Whether the unit (module 1) is running."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "running"

    def __init__(self, coordinator: DachsCoordinator) -> None:
        """Initialize the running sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_running"

    @property
    def is_on(self) -> bool | None:
        """True when the module is running."""
        data = self.coordinator.data
        return data.running if data is not None else None


class DachsMaintenanceBinarySensor(DachsEntity, BinarySensorEntity):
    """Whether maintenance is due."""

    _attr_icon = "mdi:wrench"
    _attr_translation_key = "maintenance_due"

    def __init__(self, coordinator: DachsCoordinator) -> None:
        """Initialize the maintenance sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_maintenance_due"

    @property
    def is_on(self) -> bool | None:
        """True when maintenance is due."""
        data = self.coordinator.data
        return data.maintenance_due if data is not None else None


class DachsOnlineBinarySensor(DachsEntity, BinarySensorEntity):
    """Whether the data source could reach the device (cloud modes)."""

    _attr_icon = "mdi:cloud-check"
    _attr_translation_key = "device_online"

    def __init__(self, coordinator: DachsCoordinator) -> None:
        """Initialize the online sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_device_online"

    @property
    def is_on(self) -> bool | None:
        """True when the portal reports the device as reachable.

        In failover mode this reflects the cloud view only while the
        cloud is the active data source.
        """
        data = self.coordinator.data
        return data.device_online if data is not None else None


class DachsWarningBinarySensor(DachsEntity, BinarySensorEntity):
    """Whether the unit reports an active warning (cloud2 unit banner).

    Backed by the portal's own ``warnings`` list of the connected unit
    (diagnostic view of the "Warnung steht an" banner).
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-outline"
    _attr_translation_key = "warning_pending"

    def __init__(self, coordinator: DachsCoordinator) -> None:
        """Initialize the warning sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_warning_pending"

    @property
    def is_on(self) -> bool | None:
        """True when the unit currently reports any warning."""
        details = self.coordinator.unit_details
        if details is None:
            return None
        return bool(details.warnings)
