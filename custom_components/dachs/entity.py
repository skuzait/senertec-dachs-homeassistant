"""Shared base class for Dachs entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CONNECTION,
    CONF_PRODUCT_NAME,
    CONNECTION_CLOUD,
    CONNECTION_CLOUD2,
    CONNECTION_GLT,
    CONNECTION_LOCAL,
    CONF_SERIAL,
    DOMAIN,
)
from .coordinator import DachsCoordinator

#: Connection mode → human label, shown in the device name so hubs for
#: the same unit over different transports are distinguishable.
_CONNECTION_LABELS: dict[str, str] = {
    CONNECTION_LOCAL: "MSR2 LAN",
    CONNECTION_GLT: "MSR3 Modbus",
    CONNECTION_CLOUD: "Cloud v1",
    CONNECTION_CLOUD2: "Cloud v2",
}


class DachsEntity(CoordinatorEntity[DachsCoordinator]):
    """Base entity: one device per config entry, data from the coordinator."""

    _attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry entry for this Dachs."""
        entry = self.coordinator.config_entry
        dachs = self.coordinator.data
        label = _CONNECTION_LABELS.get(entry.data.get(CONF_CONNECTION, ""))
        name = f"{entry.title} ({label})" if label else entry.title
        return DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=name,
            manufacturer="SenerTec",
            model=(
                entry.data.get(CONF_PRODUCT_NAME)
                or (dachs.part_number if dachs else None)
                or "Dachs"
            ),
            serial_number=(
                dachs.serial_number if dachs else entry.data.get(CONF_SERIAL)
            ),
        )
