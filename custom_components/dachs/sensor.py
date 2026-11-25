"""Sensors for the SenerTec Dachs integration."""

from __future__ import annotations

from typing import Any

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from senertec_dachs.cloud2 import (
    DailyElectric,
    DailyHeat,
    DailyRun,
    ShutdownSample,
)
from senertec_dachs.cloud2.models import CanIpValue
from .const import (
    CONNECTION_CLOUD2,
    CONNECTION_GLT,
    CONF_NATIVE_DATAPOINTS,
    DEFAULT_NATIVE_DATAPOINTS,
)
from .coordinator import DachsConfigEntry, DachsCoordinator
from .entity import DachsEntity
from senertec_dachs import Dachs

#: 2000-01-01 UTC in Unix seconds; the MSR2 epoch base (PDF p. 6).
_EPOCH_2000 = 946684800


@dataclass(frozen=True, kw_only=True)
class DachsSensorDescription(SensorEntityDescription):
    """Sensor description with a value function on the Dachs object."""

    value_fn: Callable[[Dachs], StateType | datetime | None]


def _commissioned(d: Dachs) -> datetime | None:
    """The commissioning date from the MSR2 epoch offset (UTC)."""
    epoch = d.commissioned_epoch_seconds
    if epoch is None:
        return None
    return datetime.fromtimestamp(_EPOCH_2000 + epoch, tz=timezone.utc)

def _last_maintenance(d: Dachs) -> datetime | None:
    """The timestamp of the last maintenance from the MSR2 epoch offset."""
    epoch = d.last_maintenance_epoch_seconds
    if epoch is None:
        return None
    return datetime.fromtimestamp(_EPOCH_2000 + epoch, tz=timezone.utc)


SENSORS: tuple[DachsSensorDescription, ...] = (
    DachsSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.power_w,
    ),
    DachsSensorDescription(
        key="electrical_energy",
        translation_key="electrical_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.electrical_energy_kwh,
    ),
    DachsSensorDescription(
        key="thermal_energy",
        translation_key="thermal_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.thermal_energy_kwh,
    ),
    DachsSensorDescription(
        key="condenser_energy",
        translation_key="condenser_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.condenser_energy_kwh,
    ),
    DachsSensorDescription(
        key="runtime",
        translation_key="runtime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.runtime_hours,
    ),
    DachsSensorDescription(
        key="starts",
        translation_key="starts",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda d: d.starts,
    ),
    DachsSensorDescription(
        key="engine_speed",
        translation_key="engine_speed",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
        value_fn=lambda d: d.engine_speed_rpm,
    ),
    DachsSensorDescription(
        key="engine_runtime",
        translation_key="engine_runtime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.engine_runtime_hours,
    ),
    # --- temperatures -------------------------------------------------------
    DachsSensorDescription(
        key="outdoor_temperature",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.outdoor_temperature,
    ),
    DachsSensorDescription(
        key="supply_temperature",
        translation_key="supply_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.supply_temperature,
    ),
    DachsSensorDescription(
        key="return_temperature",
        translation_key="return_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.return_temperature,
    ),
    DachsSensorDescription(
        key="hot_water_temperature",
        translation_key="hot_water_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.hot_water_temperature,
    ),
    DachsSensorDescription(
        key="sensor_1_temperature",
        translation_key="sensor_1_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.sensor_1_temperature,
    ),
    DachsSensorDescription(
        key="sensor_2_temperature",
        translation_key="sensor_2_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.sensor_2_temperature,
    ),
    DachsSensorDescription(
        key="sensor_3_temperature",
        translation_key="sensor_3_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.sensor_3_temperature,
    ),
    DachsSensorDescription(
        key="sensor_4_temperature",
        translation_key="sensor_4_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.sensor_4_temperature,
    ),
    DachsSensorDescription(
        key="heating_circuit_1_supply_temperature",
        translation_key="heating_circuit_1_supply_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.heating_circuit_1_supply_temperature,
    ),
    DachsSensorDescription(
        key="heating_circuit_2_supply_temperature",
        translation_key="heating_circuit_2_supply_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.heating_circuit_2_supply_temperature,
    ),
    DachsSensorDescription(
        key="exhaust_temperature",
        translation_key="exhaust_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.exhaust_temperature,
    ),
    DachsSensorDescription(
        key="engine_exhaust_temperature",
        translation_key="engine_exhaust_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.engine_exhaust_temperature,
    ),
    DachsSensorDescription(
        key="enclosure_temperature",
        translation_key="enclosure_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.enclosure_temperature,
    ),
    DachsSensorDescription(
        key="engine_coolant_temperature",
        translation_key="engine_coolant_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.engine_coolant_temperature,
    ),
    DachsSensorDescription(
        key="module_release_temperature",
        translation_key="module_release_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.module_release_temperature,
    ),
    DachsSensorDescription(
        key="generator_inlet_temperature",
        translation_key="generator_inlet_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.generator_inlet_temperature,
    ),
    DachsSensorDescription(
        key="controller_temperature",
        translation_key="controller_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.controller_temperature,
    ),
    DachsSensorDescription(
        key="supply_temperature_setpoint",
        translation_key="supply_temperature_setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.supply_temperature_setpoint,
    ),
    DachsSensorDescription(
        key="return_temperature_setpoint",
        translation_key="return_temperature_setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.return_temperature_setpoint,
    ),
    # --- diagnostics ---------------------------------------------------------
    DachsSensorDescription(
        key="fault_code",
        translation_key="fault_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle",
        value_fn=lambda d: d.fault_code,
    ),
    DachsSensorDescription(
        key="warning_code",
        translation_key="warning_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert",
        value_fn=lambda d: d.warning_code,
    ),
    DachsSensorDescription(
        key="requested_modules",
        translation_key="requested_modules",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:flash",
        value_fn=lambda d: d.requested_modules,
    ),
    DachsSensorDescription(
        key="demand_flags",
        translation_key="demand_flags",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:flag",
        value_fn=lambda d: d.demand_flags,
    ),
    DachsSensorDescription(
        key="release_flags",
        translation_key="release_flags",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:flag-outline",
        value_fn=lambda d: d.release_flags,
    ),
    DachsSensorDescription(
        key="power_demand_flags",
        translation_key="power_demand_flags",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:flag",
        value_fn=lambda d: d.power_demand_flags,
    ),
    DachsSensorDescription(
        key="power_release_flags",
        translation_key="power_release_flags",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:flag-outline",
        value_fn=lambda d: d.power_release_flags,
    ),
    DachsSensorDescription(
        key="data_fetched_at",
        translation_key="data_fetched_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.data_fetched_at,
    ),
    DachsSensorDescription(
        key="commissioned",
        translation_key="commissioned",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_commissioned,
    ),
    # --- second heat generator ------------------------------------------------
    DachsSensorDescription(
        key="second_generator_status_code",
        translation_key="second_generator_status_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.second_generator_status_code,
    ),
    DachsSensorDescription(
        key="second_generator_starts",
        translation_key="second_generator_starts",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.second_generator_starts,
    ),
    DachsSensorDescription(
        key="second_generator_runtime",
        translation_key="second_generator_runtime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.second_generator_runtime_hours,
    ),
    # --- maintenance ------------------------------------------------------------
    DachsSensorDescription(
        key="maintenance_interval",
        translation_key="maintenance_interval",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.maintenance_interval_hours,
    ),
    DachsSensorDescription(
        key="last_maintenance_runtime",
        translation_key="last_maintenance_runtime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.last_maintenance_runtime_hours,
    ),
    # --- year-end counters --------------------------------------------------------
    DachsSensorDescription(
        key="year_end_electrical_energy",
        translation_key="year_end_electrical_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.year_end_electrical_energy_kwh,
    ),
    DachsSensorDescription(
        key="year_end_thermal_energy",
        translation_key="year_end_thermal_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.year_end_thermal_energy_kwh,
    ),
    DachsSensorDescription(
        key="year_end_condenser_energy",
        translation_key="year_end_condenser_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.year_end_condenser_energy_kwh,
    ),
    DachsSensorDescription(
        key="year_end_runtime",
        translation_key="year_end_runtime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.year_end_runtime_hours,
    ),
    DachsSensorDescription(
        key="year_end_starts",
        translation_key="year_end_starts",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.year_end_starts,
    ),
    # --- heating circuit pumps and actuators (diagnostic) ---------------------
    DachsSensorDescription(
        key="heating_circuit_1_pump",
        translation_key="heating_circuit_1_pump",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:pump",
        value_fn=lambda d: d.heating_circuit_1_pump,
    ),
    DachsSensorDescription(
        key="heating_circuit_2_pump",
        translation_key="heating_circuit_2_pump",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:pump",
        value_fn=lambda d: d.heating_circuit_2_pump,
    ),
    DachsSensorDescription(
        key="circulation_pump",
        translation_key="circulation_pump",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:pump",
        value_fn=lambda d: d.circulation_pump,
    ),
    DachsSensorDescription(
        key="internal_circulation_pump",
        translation_key="internal_circulation_pump",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:pump",
        value_fn=lambda d: d.internal_circulation_pump,
    ),
    DachsSensorDescription(
        key="pre_pressure_pump",
        translation_key="pre_pressure_pump",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:pump",
        value_fn=lambda d: d.pre_pressure_pump,
    ),
    DachsSensorDescription(
        key="mixer_1_opening",
        translation_key="mixer_1_opening",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:valve-open",
        value_fn=lambda d: d.mixer_1_opening,
    ),
    DachsSensorDescription(
        key="mixer_1_closing",
        translation_key="mixer_1_closing",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:valve-closed",
        value_fn=lambda d: d.mixer_1_closing,
    ),
    DachsSensorDescription(
        key="mixer_2_opening",
        translation_key="mixer_2_opening",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:valve-open",
        value_fn=lambda d: d.mixer_2_opening,
    ),
    DachsSensorDescription(
        key="mixer_2_closing",
        translation_key="mixer_2_closing",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:valve-closed",
        value_fn=lambda d: d.mixer_2_closing,
    ),
    DachsSensorDescription(
        key="fault_relay",
        translation_key="fault_relay",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle",
        value_fn=lambda d: d.fault_relay,
    ),
    DachsSensorDescription(
        key="maintenance_relay",
        translation_key="maintenance_relay",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wrench",
        value_fn=lambda d: d.maintenance_relay,
    ),
    DachsSensorDescription(
        key="alternate_heat_enabled",
        translation_key="alternate_heat_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:fire",
        value_fn=lambda d: d.alternate_heat_enabled,
    ),
    DachsSensorDescription(
        key="programmable_output_1",
        translation_key="programmable_output_1",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:export",
        value_fn=lambda d: d.programmable_output_1,
    ),
    DachsSensorDescription(
        key="programmable_output_2",
        translation_key="programmable_output_2",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:export",
        value_fn=lambda d: d.programmable_output_2,
    ),
    DachsSensorDescription(
        key="programmable_output_3",
        translation_key="programmable_output_3",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:export",
        value_fn=lambda d: d.programmable_output_3,
    ),
    DachsSensorDescription(
        key="power_requested",
        translation_key="power_requested",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:flash",
        value_fn=lambda d: d.power_requested,
    ),
    # --- module statistics (diagnostic) ----------------------------------------
    DachsSensorDescription(
        key="max_runtime_module",
        translation_key="max_runtime_module",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:counter",
        value_fn=lambda d: d.max_runtime_module,
    ),
    DachsSensorDescription(
        key="min_runtime_module",
        translation_key="min_runtime_module",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:counter",
        value_fn=lambda d: d.min_runtime_module,
    ),
    DachsSensorDescription(
        key="most_starts_module",
        translation_key="most_starts_module",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:counter",
        value_fn=lambda d: d.most_starts_module,
    ),
    DachsSensorDescription(
        key="fewest_starts_module",
        translation_key="fewest_starts_module",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:counter",
        value_fn=lambda d: d.fewest_starts_module,
    ),
    DachsSensorDescription(
        key="most_starts",
        translation_key="most_starts",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda d: d.most_starts,
    ),
    DachsSensorDescription(
        key="fewest_starts",
        translation_key="fewest_starts",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda d: d.fewest_starts,
    ),
    DachsSensorDescription(
        key="max_maintenance_module",
        translation_key="max_maintenance_module",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:counter",
        value_fn=lambda d: d.max_maintenance_module,
    ),
    DachsSensorDescription(
        key="min_maintenance_module",
        translation_key="min_maintenance_module",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:counter",
        value_fn=lambda d: d.min_maintenance_module,
    ),
    # --- second generator extras (diagnostic) ----------------------------------
    DachsSensorDescription(
        key="second_generator_warning_code",
        translation_key="second_generator_warning_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert",
        value_fn=lambda d: d.second_generator_warning_code,
    ),
    DachsSensorDescription(
        key="second_generator_demand_flags",
        translation_key="second_generator_demand_flags",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:flag",
        value_fn=lambda d: d.second_generator_demand_flags,
    ),
    DachsSensorDescription(
        key="second_generator_release_flags",
        translation_key="second_generator_release_flags",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:flag-outline",
        value_fn=lambda d: d.second_generator_release_flags,
    ),
    # --- maintenance timestamps (diagnostic) -----------------------------------
    DachsSensorDescription(
        key="last_maintenance_date",
        translation_key="last_maintenance_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_last_maintenance,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DachsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add all Dachs sensors for this config entry."""
    coordinator = entry.runtime_data
    # The portal poll timestamp only exists where the portal is involved.
    base: list[DachsSensorDescription] = [
        description
        for description in SENSORS
        if coordinator.is_cloud or description.key != "data_fetched_at"
    ]

    added = False

    def _async_add_facade() -> None:
        """Create the facade sensors once, when the first data exists.

        Non-blocking setup forwards platforms before the first refresh
        has landed. GLT/cloud2 get no placeholder entities for readings
        their backend cannot answer, so on those backends the facade
        sensors are deferred until real data exists.
        """
        nonlocal added
        if added:
            return
        data = coordinator.data
        if data is None:
            return  # first refresh still in flight; stay subscribed
        added = True
        descriptions = base
        if coordinator.mode in (CONNECTION_GLT, CONNECTION_CLOUD2):
            # These backends supply a subset of the MSR2 key space; the
            # library answers None for absent keys, so those readings
            # get no placeholder entity at all.
            descriptions = [
                description
                for description in base
                if description.value_fn(data) is not None
            ]
        async_add_entities(
            DachsSensor(coordinator, description) for description in descriptions
        )
        if coordinator.mode == CONNECTION_CLOUD2 and entry.data.get(
            CONF_NATIVE_DATAPOINTS, DEFAULT_NATIVE_DATAPOINTS
        ):
            _async_setup_native_sensors(coordinator, async_add_entities)

    if coordinator.data is not None:
        _async_add_facade()
    else:
        coordinator.attach_platform_listener(_async_add_facade)
    if coordinator.mode == CONNECTION_CLOUD2:
        _setup_daily_sensors(coordinator, async_add_entities)


def _async_setup_native_sensors(
    coordinator: DachsCoordinator,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the dynamic native cloud2 datapoint sensors.

    Datapoints are discovered live: whatever the coordinator's native
    listener has already admitted becomes an entity right away, and the
    platform callback below grows the entity list as newly admitted
    datapoint ids arrive. The callback unsub lives on the coordinator;
    its shutdown removes it again (see
    :meth:`DachsCoordinator.attach_platform_listener`).
    """
    added: set[str] = set()

    def _async_add_seen() -> None:
        new = [
            key
            for key in coordinator.native_values
            if key not in added
        ]
        if not new:
            return
        added.update(new)
        async_add_entities(
            NativeDachsSensor(coordinator, key) for key in new
        )

    _async_add_seen()
    coordinator.attach_platform_listener(_async_add_seen)


# --- cloud2 daily cards (portal chart endpoints) -----------------------------

@dataclass(frozen=True, kw_only=True)
class DachsDailyDescription(SensorEntityDescription):
    """One daily-card sensor reading from the coordinator's history."""

    value_fn: Callable[[DachsCoordinator], StateType | datetime | None]
    has_data_fn: Callable[[DachsCoordinator], bool] = lambda coordinator: True


def _last_electric(coordinator: DachsCoordinator) -> DailyElectric | None:
    """The newest DailyElectric row (today's running total, or None)."""
    rows = coordinator.history.get("electric") or []
    return rows[-1] if rows else None


def _last_heat(coordinator: DachsCoordinator) -> DailyHeat | None:
    rows = coordinator.history.get("heat") or []
    return rows[-1] if rows else None


def _last_run(coordinator: DachsCoordinator) -> DailyRun | None:
    rows = coordinator.history.get("run") or []
    return rows[-1] if rows else None


def _shutdown_reason(coordinator: DachsCoordinator) -> str | int | None:
    """Reason text of the newest informative sample today.

    The portal logs "No demand" rows every hour; the useful answer is
    the newest non-"No demand" reason of the current day, falling back
    to the plain newest sample.
    """
    samples = coordinator.history.get("shutdown") or []
    if not samples:
        return None
    today = dt_util.now().date()
    todays = [
        sample
        for sample in samples
        if dt_util.as_local(sample.at).date() == today
    ]
    for sample in reversed(todays):
        if isinstance(sample.reason, str) and sample.reason.casefold() == "no demand":
            continue
        return sample.reason
    if todays:
        return todays[-1].reason
    return samples[-1].reason


def _shutdown_samples_attr(
    coordinator: DachsCoordinator,
) -> dict[str, str | int | None]:
    """Up to ~50 recent samples as ISO-timestamp → reason text."""
    samples = coordinator.history.get("shutdown") or []
    return {
        sample.at.isoformat(): sample.reason
        for sample in samples[-50:]
    }


DAILY_SENSORS: tuple[DachsDailyDescription, ...] = (
    DachsDailyDescription(
        key="daily_electric",
        translation_key="daily_electric",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda coordinator: (
            produced.self_consumed_kwh + produced.fed_in_kwh
            if (produced := _last_electric(coordinator)) is not None
            else None
        ),
        has_data_fn=lambda coordinator: bool(coordinator.history.get("electric")),
    ),
    DachsDailyDescription(
        key="daily_self_consumed",
        translation_key="daily_self_consumed",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda coordinator: (
            produced.self_consumed_kwh
            if (produced := _last_electric(coordinator)) is not None
            else None
        ),
        has_data_fn=lambda coordinator: bool(coordinator.history.get("electric")),
    ),
    DachsDailyDescription(
        key="daily_feedin",
        translation_key="daily_feedin",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda coordinator: (
            produced.fed_in_kwh
            if (produced := _last_electric(coordinator)) is not None
            else None
        ),
        has_data_fn=lambda coordinator: bool(coordinator.history.get("electric")),
    ),
    DachsDailyDescription(
        key="daily_grid_import",
        translation_key="daily_grid_import",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda coordinator: (
            produced.from_grid_kwh
            if (produced := _last_electric(coordinator)) is not None
            else None
        ),
        has_data_fn=lambda coordinator: bool(coordinator.history.get("electric")),
    ),
    DachsDailyDescription(
        key="daily_grid_export",
        translation_key="daily_grid_export",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda coordinator: (
            produced.to_grid_kwh
            if (produced := _last_electric(coordinator)) is not None
            else None
        ),
        has_data_fn=lambda coordinator: bool(coordinator.history.get("electric")),
    ),
    DachsDailyDescription(
        key="daily_heat",
        translation_key="daily_heat",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda coordinator: (
            produced.produced_kwh
            if (produced := _last_heat(coordinator)) is not None
            else None
        ),
        has_data_fn=lambda coordinator: bool(coordinator.history.get("heat")),
    ),
    DachsDailyDescription(
        key="daily_hours",
        translation_key="daily_hours",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda coordinator: (
            produced.hours
            if (produced := _last_run(coordinator)) is not None
            else None
        ),
        has_data_fn=lambda coordinator: bool(coordinator.history.get("run")),
    ),
    DachsDailyDescription(
        key="daily_starts",
        translation_key="daily_starts",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda coordinator: (
            produced.starts
            if (produced := _last_run(coordinator)) is not None
            else None
        ),
        has_data_fn=lambda coordinator: bool(coordinator.history.get("run")),
    ),
    DachsDailyDescription(
        key="shutdown_reason",
        translation_key="shutdown_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:power-off",
        value_fn=_shutdown_reason,
        has_data_fn=lambda coordinator: bool(coordinator.history.get("shutdown")),
    ),
)


def _setup_daily_sensors(
    coordinator: DachsCoordinator,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the daily-card sensors once the portal history is available.

    Lazy like the native datapoints: with a non-blocking setup the
    history fetch lands with the first coordinator refresh, and the
    callback below creates the entities at that moment. Each entity
    then follows the normal coordinator cycle.
    """
    added = False

    def _async_add_when_available() -> None:
        nonlocal added
        if added:
            return
        if coordinator.unit_details is None and not any(
            coordinator.history.values()
        ):
            return
        added = True
        async_add_entities(
            DachsDailySensor(coordinator, description)
            for description in DAILY_SENSORS
        )

    _async_add_when_available()
    coordinator.attach_platform_listener(_async_add_when_available)


class DachsDailySensor(DachsEntity, SensorEntity):
    """One daily card fed from the portal's own chart endpoints (cloud2)."""

    entity_description: DachsDailyDescription

    def __init__(
        self,
        coordinator: DachsCoordinator,
        description: DachsDailyDescription,
    ) -> None:
        """Initialize the daily sensor from its description."""
        super().__init__(coordinator)
        self.entity_description = description
        # Translation key → unique id: "daily_grid_import" →
        # "-daily-grid-import".
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-{description.key.replace('_', '-')}"
        )

    @property
    def available(self) -> bool:
        """Unknown while the chart data for this card is missing."""
        return self.coordinator.last_update_success and self.entity_description.has_data_fn(
            self.coordinator
        )

    @property
    def native_value(self) -> StateType | datetime | None:
        """Today's running total, or the requested history answer."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Recent shutdown samples, newest included, for diagnostics."""
        if self.entity_description.key != "shutdown_reason":
            return None
        return {"samples": _shutdown_samples_attr(self.coordinator)}


@dataclass(frozen=True)
class _NativeSensorSpec:
    """How a portal unit string maps to a Home Assistant sensor."""

    device_class: SensorDeviceClass | None
    native_unit: str | None
    state_class: SensorStateClass | None


# The portal's own unit strings — mapped, never guessed beyond this
# table: unknown units keep the unit as-is with no device class.
_NATIVE_UNIT_MAP: dict[str, _NativeSensorSpec] = {
    "°C": _NativeSensorSpec(
        SensorDeviceClass.TEMPERATURE, "°C", SensorStateClass.MEASUREMENT
    ),
    "W": _NativeSensorSpec(
        SensorDeviceClass.POWER, UnitOfPower.WATT, None
    ),
    "kW": _NativeSensorSpec(
        SensorDeviceClass.POWER, UnitOfPower.KILO_WATT, None
    ),
    "kWh": _NativeSensorSpec(
        SensorDeviceClass.ENERGY,
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorStateClass.TOTAL_INCREASING,
    ),
    "V": _NativeSensorSpec(SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, None),
    "A": _NativeSensorSpec(SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, None),
    "Hz": _NativeSensorSpec(
        SensorDeviceClass.FREQUENCY, UnitOfFrequency.HERTZ, None
    ),
    "%": _NativeSensorSpec(None, "%", None),
    "Hours": _NativeSensorSpec(SensorDeviceClass.DURATION, UnitOfTime.HOURS, None),
    "h": _NativeSensorSpec(SensorDeviceClass.DURATION, UnitOfTime.HOURS, None),
    "Min": _NativeSensorSpec(SensorDeviceClass.DURATION, UnitOfTime.MINUTES, None),
    "min": _NativeSensorSpec(SensorDeviceClass.DURATION, UnitOfTime.MINUTES, None),
    "Sec": _NativeSensorSpec(SensorDeviceClass.DURATION, UnitOfTime.SECONDS, None),
    "Days": _NativeSensorSpec(SensorDeviceClass.DURATION, UnitOfTime.DAYS, None),
    "Day": _NativeSensorSpec(SensorDeviceClass.DURATION, UnitOfTime.DAYS, None),
    "bar": _NativeSensorSpec(SensorDeviceClass.PRESSURE, UnitOfPressure.BAR, None),
}

# Elements of one array code, for the unique id ("AM029[2]" → "-2").
_ARRAY_INDEX_RE = re.compile(r"\[(\d+)\]\Z")


class NativeDachsSensor(DachsEntity, SensorEntity):
    """One native cloud2 datapoint admitted by the library display filter.

    The library has already curated what shows up — only admitted
    values exist in the coordinator, so this sensor only maps the
    admitted value to Home Assistant's three native shapes:

    - units from the portal (measurements) — live in the unit map;
    - translated enum states — simple sensor, no unit/state class;
    - epoch-ms timestamps the filter converted — TIMESTAMP device class.
    """

    def __init__(self, coordinator: DachsCoordinator, key: str) -> None:
        """Initialize from the value currently held by the coordinator."""
        super().__init__(coordinator)
        self._key = key
        value = coordinator.native_values[key]
        entry = coordinator.config_entry
        unique_id = f"{entry.entry_id}-native-{value.id}"
        index_match = _ARRAY_INDEX_RE.search(value.code)
        if index_match:
            unique_id += f"-{index_match.group(1)}"
        self._attr_unique_id = unique_id
        self._attr_name = value.name
        if isinstance(value.value, datetime):
            # Filter-converted epoch-ms timestamp.
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
            self._attr_native_unit_of_measurement = None
            self._attr_state_class = None
        elif isinstance(value.value, (str, bool)):
            # Translated enumeration state; portal names it already.
            self._attr_device_class = None
            self._attr_native_unit_of_measurement = None
            self._attr_state_class = None
        else:
            spec = _NATIVE_UNIT_MAP.get(value.unit or "")
            if spec is None:
                # Portal unit outside the map: unit passed through as-is,
                # no device class, no state class.
                self._attr_device_class = None
                self._attr_native_unit_of_measurement = value.unit
                self._attr_state_class = None
            else:
                self._attr_device_class = spec.device_class
                self._attr_native_unit_of_measurement = spec.native_unit
                self._attr_state_class = spec.state_class

    @property
    def native_value(self) -> StateType:
        """The gain-applied value, or the enum text, of the datapoint."""
        value = self.coordinator.native_values.get(self._key)
        return value.value if value is not None else None


class DachsSensor(DachsEntity, SensorEntity):
    """A single Dachs reading."""

    entity_description: DachsSensorDescription

    def __init__(
        self,
        coordinator: DachsCoordinator,
        description: DachsSensorDescription,
    ) -> None:
        """Initialize the sensor from its description."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> StateType | datetime | None:
        """The typed reading, or None when not cleanly available."""
        data = self.coordinator.data
        if data is None:
            # Non-blocking setup: the first background refresh may not
            # have landed yet.
            return None
        return self.entity_description.value_fn(data)
