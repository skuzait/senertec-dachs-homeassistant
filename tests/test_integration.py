"""Integration tests: setup, entities, controls across all backends."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from senertec_dachs import Dachs, DachsError
from senertec_dachs.cloud2.models import CanIpValue

from custom_components.dachs.const import DOMAIN

from fake_dachs import CloudPortalFake, LocalServerFake
from fake_dachs import FakeCloud2Native
from fake_glt import FakeGltServer


def _entity_ids(hass: HomeAssistant, entry) -> dict[str, str]:
    """Map unique_id to entity_id for all of the entry's registry entries."""
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    return {e.unique_id: e.entity_id for e in entries}


async def _wait_for_data(hass: HomeAssistant, entry) -> None:
    """Wait until the background first refresh has landed.

    Setup is non-blocking; the refresh task usually finishes before
    the wait returns, but an extra synchronous refresh removes the
    race so the entity assertions below see real data.
    """
    coordinator = entry.runtime_data
    await hass.async_block_till_done(wait_background_tasks=True)
    if coordinator.data is None:
        await coordinator.async_refresh()
        await hass.async_block_till_done()


def _local_entry(port: int) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"local:127.0.0.1:{port}",
        title="Dachs 0000000001",
        data={
            "connection": "local",
            "host": "127.0.0.1",
            "port": port,
            "username": "glt",
            "password": "",
        },
    )


def _cloud_entry(base_url: str) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="cloud:12345",
        title="Dachs 0000000001",
        data={
            "connection": "cloud",
            "portal_id": "12345",
            "portal_password": "secret",
            "base_url": base_url,
        },
    )


def _glt_entry(host: str, port: int) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"glt:{host}:{port}",
        title="Dachs 5.5 (G5.5)",
        data={
            "connection": "glt",
            "host": host,
            "port": port,
            "pin": "",
            "product_name": "Dachs 5.5 (G5.5)",
        },
    )


class _FakeCloud2Dachs:
    """Minimal Dachs facade stub for cloud2 coordinator wiring."""

    def __init__(self) -> None:
        self.serial_number = "96385"
        self.part_number = None
        self.power_w = 5500
        self.electrical_energy_kwh = Decimal("430076.3")
        self.running = True
        self.device_online = True
        self.data_fetched_at = dt_util.utcnow()
        self.snapshot = None
        self.updates = 0
        self.closed = False

    async def update(self) -> "_FakeCloud2Dachs":
        self.updates += 1
        return self

    async def close(self) -> None:
        self.closed = True

    def __getattr__(self, name: str):
        # Everything the facade would answer None for on cloud2
        # (MSR2-specific keys) stays honestly missing here too.
        return None


def _cloud2_entry(**overrides: object) -> MockConfigEntry:
    data: dict[str, object] = {
        "connection": "cloud2",
        "email": "you@example.com",
        "password": "secret",
        "serial": "96385",
        "product_name": "Dachs 5.5",
        "native_datapoints": True,
    }
    data.update(overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="cloud2:96385",
        title="Dachs 5.5 (96385)",
        data=data,
    )


async def test_glt_setup_exposes_entities(hass: HomeAssistant) -> None:
    """MSR3 Modbus setup creates reading entities but no write entities."""
    fake = FakeGltServer()
    await fake.start()
    entry = _glt_entry(fake.host, fake.port)
    entry.add_to_hass(hass)
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)
        assert entry.runtime_data.update_interval == timedelta(seconds=30)

        entity_ids = _entity_ids(hass, entry)
        power = hass.states.get(entity_ids[f"{entry.entry_id}_power"])
        assert power.state == "5500"
        assert power.attributes["unit_of_measurement"] == "W"

        electrical = hass.states.get(entity_ids[f"{entry.entry_id}_electrical_energy"])
        assert electrical.state == "430076.3"

        runtime = hass.states.get(entity_ids[f"{entry.entry_id}_runtime"])
        assert runtime.state == "12657"

        outdoor = hass.states.get(entity_ids[f"{entry.entry_id}_outdoor_temperature"])
        assert outdoor.state == "22.8"

        # MSR2-only controls must not exist on the GLT backend.
        assert f"{entry.entry_id}_request_run" not in entity_ids
        assert f"{entry.entry_id}_power_demand" not in entity_ids
        # Absent MSR2 readings get no placeholder sensor.
        assert f"{entry.entry_id}_commissioned" not in entity_ids
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        await fake.stop()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_cloud2_setup_exposes_shared_entities(hass: HomeAssistant) -> None:
    """cloud2 setup wires the coordinator to the DachsConnect facade."""
    fake = _FakeCloud2Dachs()
    entry = _cloud2_entry()
    entry.add_to_hass(hass)
    with patch.object(
        Dachs, "cloud2", lambda email, password, serial=None, cookies=None: fake
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)
        assert entry.runtime_data.update_interval == timedelta(seconds=120)

        entity_ids = _entity_ids(hass, entry)
        power = hass.states.get(entity_ids[f"{entry.entry_id}_power"])
        assert power.state == "5500"

        electrical = hass.states.get(entity_ids[f"{entry.entry_id}_electrical_energy"])
        assert electrical.state == "430076.3"

        online = hass.states.get(entity_ids[f"{entry.entry_id}_device_online"])
        assert online.state == "on"

        fetched_at = hass.states.get(entity_ids[f"{entry.entry_id}_data_fetched_at"])
        assert fetched_at is not None

        # No MSR2 module-based write entities on cloud2.
        assert f"{entry.entry_id}_request_run" not in entity_ids
        assert f"{entry.entry_id}_power_demand" not in entity_ids
        assert fake.updates == 1

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert fake.closed
        assert entry.state is ConfigEntryState.NOT_LOADED


async def test_local_setup_exposes_entities(hass: HomeAssistant) -> None:
    """Setup creates the sensor and control entities with live values."""
    fake = LocalServerFake()
    port = await fake.start()
    entry = _local_entry(port)
    entry.add_to_hass(hass)
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)
        assert entry.runtime_data.update_interval == timedelta(seconds=30)

        entity_ids = _entity_ids(hass, entry)
        power = hass.states.get(entity_ids[f"{entry.entry_id}_power"])
        assert power is not None
        assert power.state == "5522"
        assert power.attributes["unit_of_measurement"] == "W"

        electrical = hass.states.get(entity_ids[f"{entry.entry_id}_electrical_energy"])
        assert electrical.state == "429853.864"
        assert electrical.attributes["device_class"] == "energy"
        assert electrical.attributes["state_class"] == "total_increasing"

        outdoor = hass.states.get(entity_ids[f"{entry.entry_id}_outdoor_temperature"])
        assert outdoor.state == "9"

        running = hass.states.get(entity_ids[f"{entry.entry_id}_running"])
        assert running.state == "on"

        maintenance = hass.states.get(
            entity_ids[f"{entry.entry_id}_maintenance_due"]
        )
        assert maintenance.state == "off"

        # Unconnected sensors surface as unknown, not fabricated values.
        fuehler3 = hass.states.get(
            entity_ids[f"{entry.entry_id}_controller_temperature"]
        )
        assert fuehler3.state == "30"

        requested = hass.states.get(
            entity_ids[f"{entry.entry_id}_requested_modules"]
        )
        assert requested.state == "2"
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        await fake.stop()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_button_sends_documented_demand(hass: HomeAssistant) -> None:
    """The run button writes the two documented GLT fields."""
    fake = LocalServerFake()
    port = await fake.start()
    entry = _local_entry(port)
    entry.add_to_hass(hass)
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)

        entity_ids = _entity_ids(hass, entry)
        button_id = entity_ids[f"{entry.entry_id}_request_run"]
        await hass.services.async_call(
            "button", "press", {"entity_id": button_id}, blocking=True
        )
        assert fake.posts == [
            {
                "Stromf_Ew.Anforderung_GLT.bAktiv": "1",
                "Stromf_Ew.Anforderung_GLT.bAnzahlModule": "1",
            }
        ]
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        await fake.stop()


async def test_number_sends_module_count(hass: HomeAssistant) -> None:
    """Setting the power-demand number writes the module count."""
    fake = LocalServerFake()
    port = await fake.start()
    entry = _local_entry(port)
    entry.add_to_hass(hass)
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)

        entity_ids = _entity_ids(hass, entry)
        number_id = entity_ids[f"{entry.entry_id}_power_demand"]
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": number_id, "value": 3},
            blocking=True,
        )
        assert fake.posts == [
            {
                "Stromf_Ew.Anforderung_GLT.bAktiv": "1",
                "Stromf_Ew.Anforderung_GLT.bAnzahlModule": "3",
            }
        ]
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        await fake.stop()


async def test_cloud_setup_exposes_online_entities(hass: HomeAssistant) -> None:
    """Cloud mode adds the portal-reachability binary sensor."""
    portal = CloudPortalFake()
    await portal.start()
    entry = _cloud_entry(portal.url())
    entry.add_to_hass(hass)
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)
        assert entry.runtime_data.update_interval == timedelta(seconds=120)

        entity_ids = _entity_ids(hass, entry)

        online = hass.states.get(entity_ids[f"{entry.entry_id}_device_online"])
        assert online.state == "on"

        fetched_at = hass.states.get(entity_ids[f"{entry.entry_id}_data_fetched_at"])
        assert fetched_at is not None
        assert fetched_at.state != "unknown"
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        await portal.stop()


async def test_cloud_http_500_keeps_polling_and_recovers(hass: HomeAssistant) -> None:
    """A portal HTTP 500 must degrade gracefully and self-heal.

    Regression: HttpError escaped _async_update_data, the coordinator
    logged "Unexpected error" and stopped polling until a reload.
    """
    portal = CloudPortalFake()
    await portal.start()
    entry = _cloud_entry(portal.url())
    entry.add_to_hass(hass)
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)
        coordinator = entry.runtime_data
        assert coordinator.last_update_success

        portal.metainfo_status = 500
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert coordinator.last_update_success is False
        assert isinstance(coordinator.last_exception, UpdateFailed)

        # The polling loop must still be scheduled: recovery happens on
        # its own once the portal answers again. The scheduled refresh
        # runs as a background task, so wait for background tasks too.
        portal.metainfo_status = 200
        async_fire_time_changed(
            hass, dt_util.utcnow() + coordinator.update_interval + timedelta(seconds=5)
        )
        await _wait_for_data(hass, entry)
        assert coordinator.last_update_success is True
        assert coordinator.data.snapshot is not None
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


def _native_value(**overrides: object) -> CanIpValue:
    """A representative live value frame from the cloud2 listener.

    Numbers as filter-passing "measurement": named, unit-tagged.
    """
    fields: dict[str, object] = {
        "code": "MM029",
        "board": "CU-CHP01",
        "id": "kP3EngineTemp",
        "raw": 3890,
        "value": Decimal("38.9"),
        "unit": "°C",
        "gain": Decimal("0.01"),
        "enum_name": None,
        "age_seconds": 0,
        "name": "Abgastemperatur Motor",
    }
    fields.update(overrides)
    return CanIpValue(**fields)  # type: ignore[arg-type]


async def test_cloud2_native_datapoints_listener_and_sensors(
    hass: HomeAssistant,
) -> None:
    """The cloud2 listener feeds dynamic native sensors from live frames."""
    fake_cloud2 = FakeCloud2Native()
    fake = _FakeCloud2Dachs()
    fake.client = fake_cloud2.client
    entry = _cloud2_entry()
    entry.add_to_hass(hass)
    with patch.object(Dachs, "cloud2", lambda email, password, serial=None, cookies=None: fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)

        # The listener is started once on the cloud2 client after setup.
        fake_cloud2.client.start_listener.assert_called_once()
        on_value = fake_cloud2.on_value
        entry_id = entry.entry_id

        # A first live value creates its sensor (after the ~1s debounce).
        on_value(_native_value())
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
        await hass.async_block_till_done()

        entity_ids = _entity_ids(hass, entry)
        native_keys = [
            key for key in entity_ids if key.startswith(f"{entry_id}-native-")
        ]
        assert native_keys == [f"{entry_id}-native-kP3EngineTemp"]
        state = hass.states.get(entity_ids[native_keys[0]])
        assert state.state == "38.9"
        assert state.attributes["device_class"] == "temperature"
        assert state.attributes["unit_of_measurement"] == "°C"
        assert state.attributes["state_class"] == "measurement"
        assert state.attributes["friendly_name"].endswith("Abgastemperatur Motor")

        # Unnamed array elements beyond index 0 are rejected by the
        # filter; only the current element (index 0) exists, under the
        # plain portal name. The unique id keeps its index suffix.
        on_value(_native_value(code="BM001[2]", value=Decimal("2.4"), raw=2400))
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
        await hass.async_block_till_done()
        entity_ids = _entity_ids(hass, entry)
        assert f"{entry_id}-native-kP3EngineTemp-2" not in entity_ids

        on_value(_native_value(code="BM001[0]", value=Decimal("2.4"), raw=2400))
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
        await hass.async_block_till_done()
        entity_ids = _entity_ids(hass, entry)
        array_sensor = hass.states.get(
            entity_ids[f"{entry_id}-native-kP3EngineTemp-0"]
        )
        assert array_sensor is not None
        assert (
            array_sensor.attributes["friendly_name"].endswith(
                "Abgastemperatur Motor"
            )
        )
        assert "[0]" not in array_sensor.attributes["friendly_name"]

        # Unload stops the listener again.
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        fake_cloud2.client.stop_listener.assert_called_once()
        assert entry.state is ConfigEntryState.NOT_LOADED


async def test_cloud2_native_datapoints_disabled_runs_no_listener(
    hass: HomeAssistant,
) -> None:
    """With the option off, no native listener runs and none is stopped."""
    fake_cloud2 = FakeCloud2Native()
    fake = _FakeCloud2Dachs()
    fake.client = fake_cloud2.client
    entry = _cloud2_entry(native_datapoints=False)
    entry.add_to_hass(hass)
    with patch.object(Dachs, "cloud2", lambda email, password, serial=None, cookies=None: fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)

        fake_cloud2.client.start_listener.assert_not_called()
        entity_ids = _entity_ids(hass, entry)
        assert not [
            key for key in entity_ids if key.startswith(f"{entry.entry_id}-native-")
        ]
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        fake_cloud2.client.stop_listener.assert_not_called()


async def test_cloud2_native_filter_layers(hass: HomeAssistant) -> None:
    """Only admitted datapoints become entities; the library curates.

    Exercises the library display filter through the integration:
    normal measurement, mirror dedupe, junk tokens, timestamps,
    currency and unit-less counters.
    """
    fake_cloud2 = FakeCloud2Native()
    fake = _FakeCloud2Dachs()
    fake.client = fake_cloud2.client
    entry = _cloud2_entry()
    entry.add_to_hass(hass)
    with patch.object(Dachs, "cloud2", lambda email, password, serial=None, cookies=None: fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)

        async def deliver(*values: CanIpValue) -> None:
            for value in values:
                fake_cloud2.deliver(value)
            async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
            await hass.async_block_till_done()

        def native_entity_ids() -> dict[str, str]:
            return {
                key: value
                for key, value in _entity_ids(hass, entry).items()
                if key.startswith(f"{entry.entry_id}-native-")
            }

        # Normal measurement with display name and unit: admitted.
        await deliver(_native_value())
        entity_ids = native_entity_ids()
        assert list(entity_ids) == [f"{entry.entry_id}-native-kP3EngineTemp"]
        engine_sensor = hass.states.get(
            entity_ids[f"{entry.entry_id}-native-kP3EngineTemp"]
        )
        assert engine_sensor.state == "38.9"
        assert engine_sensor.attributes["device_class"] == "temperature"
        assert engine_sensor.attributes["state_class"] == "measurement"

        # Mirror board carrying the same display name: kept as its own
        # entity, disambiguated by board prefix (library semantics).
        await deliver(
            _native_value(board="EM", id="EM0EngineTemp", code="MM029E")
        )
        entity_ids = native_entity_ids()
        mirror = hass.states.get(entity_ids[f"{entry.entry_id}-native-EM0EngineTemp"])
        assert (
            mirror.attributes["friendly_name"].endswith("EM Abgastemperatur Motor")
        )
        assert mirror.attributes["unit_of_measurement"] == "°C"

        # Later frames must not change either entity's name: the name
        # was resolved from the admitted value at creation time.
        await deliver(
            _native_value(),
            _native_value(board="EM", id="EM0EngineTemp", code="MM029E"),
        )
        assert (
            hass.states.get(entity_ids[f"{entry.entry_id}-native-kP3EngineTemp"])
            .attributes["friendly_name"]
            .endswith("Abgastemperatur Motor")
        )
        assert (
            hass.states.get(entity_ids[f"{entry.entry_id}-native-EM0EngineTemp"])
            .attributes["friendly_name"]
            .endswith("EM Abgastemperatur Motor")
        )

        # Portal debug token ids never get a display name: rejected.
        await deliver(_native_value(id="tmyRBbn48McrM0123", name=None))
        assert len(native_entity_ids()) == 2

        # Epoch-ms timestamp: converted, exposed as TIMESTAMP sensor.
        await deliver(
            _native_value(
                id="YX5KpmnFqBXGf8uBJiS",
                code="MM917",
                raw=1763372189400,
                value=Decimal("1763372189400"),
                unit=None,
                name="Date last maintnce",
            )
        )
        entity_ids = native_entity_ids()
        ts = hass.states.get(entity_ids[f"{entry.entry_id}-native-YX5KpmnFqBXGf8uBJiS"])
        assert ts.attributes["device_class"] == "timestamp"
        assert ts.state.startswith("2025-11-17T")
        assert "unit_of_measurement" not in ts.attributes

        # Enum state: simple sensor, no unit/state class.
        await deliver(
            _native_value(
                id="gUD6hGtnrFYrbm99qbxqGi",
                code="MM201",
                raw=1,
                value="Standby",
                unit=None,
                enum_name="BrennerStatus",
                name="Operating state",
            )
        )
        entity_ids = native_entity_ids()
        enum_sensor = hass.states.get(
            entity_ids[f"{entry.entry_id}-native-gUD6hGtnrFYrbm99qbxqGi"]
        )
        assert enum_sensor.state == "Standby"
        assert "unit_of_measurement" not in enum_sensor.attributes
        assert "state_class" not in enum_sensor.attributes

        # Rejects stay rejects: currency, unit-less counters.
        await deliver(
            _native_value(id="price", code="MM500", raw=1000, value=Decimal("1000"), unit="€", name="Price"),
            _native_value(id="entries", code="MM501", raw=40, value=Decimal("40"), unit=None, name="Number of entries"),
        )
        assert len(native_entity_ids()) == 4

        # Registry claim: exactly four native entities with admitted
        # ids only — junk never reached it (canonical and its EM mirror
        # are distinct ids and distinct names).
        assert sorted(native_entity_ids()) == [
            f"{entry.entry_id}-native-EM0EngineTemp",
            f"{entry.entry_id}-native-YX5KpmnFqBXGf8uBJiS",
            f"{entry.entry_id}-native-gUD6hGtnrFYrbm99qbxqGi",
            f"{entry.entry_id}-native-kP3EngineTemp",
        ]


_DAILY_SUFFIXES = (
    "-daily-electric",
    "-daily-self-consumed",
    "-daily-feedin",
    "-daily-grid-import",
    "-daily-grid-export",
    "-daily-heat",
    "-daily-hours",
    "-daily-starts",
    "-shutdown-reason",
)


def _daily_entity_ids(entity_ids: dict[str, str]) -> dict[str, str]:
    """The daily-card entities of one entry's registry slice."""
    return {
        key: value
        for key, value in entity_ids.items()
        if key.endswith(_DAILY_SUFFIXES)
    }


async def test_cloud2_daily_history_entities(hass: HomeAssistant) -> None:
    """The cloud2 daily cards show today's running totals and warnings."""
    fake_cloud2 = FakeCloud2Native()
    fake = _FakeCloud2Dachs()
    fake.client = fake_cloud2.client
    entry = _cloud2_entry()
    entry.add_to_hass(hass)
    with patch.object(Dachs, "cloud2", lambda email, password, serial=None, cookies=None: fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)

        entity_ids = _entity_ids(hass, entry)
        daily = _daily_entity_ids(entity_ids)
        assert sorted(daily) == sorted(
            f"{entry.entry_id}{suffix}" for suffix in _DAILY_SUFFIXES
        )

        expectations = {
            "daily-electric": "3.5",  # self consumed 3.1 + fed in 0.4
            "daily-self-consumed": "3.1",
            "daily-feedin": "0.4",
            "daily-grid-import": "1.7",
            "daily-grid-export": "0.1",
            "daily-heat": "9.4",
            "daily-hours": "2.5",
            "daily-starts": "3",
        }
        for suffix, expected in expectations.items():
            state = hass.states.get(daily[f"{entry.entry_id}-{suffix}"])
            assert state is not None, suffix
            assert state.state == expected, suffix
        electric = hass.states.get(daily[f"{entry.entry_id}-daily-electric"])
        assert electric.attributes["unit_of_measurement"] == "kWh"
        assert electric.attributes["device_class"] == "energy"

        # Shutdown reason: newest informative sample of today.
        reason = hass.states.get(daily[f"{entry.entry_id}-shutdown-reason"])
        assert reason.state == "Heat demand satisfied"
        samples = reason.attributes.get("samples")
        assert samples and all("T" in key for key in samples)

        # The portal's own unit banner: active warnings.
        warning = hass.states.get(entity_ids[f"{entry.entry_id}_warning_pending"])
        assert warning.state == "on"

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_local_mode_has_no_daily_or_warning_entities(
    hass: HomeAssistant,
) -> None:
    """Daily cards and the warning binary are cloud2-only."""
    fake = LocalServerFake()
    port = await fake.start()
    entry = _local_entry(port)
    entry.add_to_hass(hass)
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)

        entity_ids = _entity_ids(hass, entry)
        assert not _daily_entity_ids(entity_ids)
        assert f"{entry.entry_id}_warning_pending" not in entity_ids
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        await fake.stop()


async def test_cloud2_history_failure_keeps_previous(hass: HomeAssistant) -> None:
    """One failing chart endpoint keeps its old data; the cycle survives."""
    fake_cloud2 = FakeCloud2Native()
    fake = _FakeCloud2Dachs()
    fake.client = fake_cloud2.client
    entry = _cloud2_entry()
    entry.add_to_hass(hass)
    with patch.object(Dachs, "cloud2", lambda email, password, serial=None, cookies=None: fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)
        coordinator = entry.runtime_data
        old_heat = coordinator.history["heat"]
        assert old_heat

        fake_cloud2.client.daily_heat.side_effect = DachsError("chart broke")
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert coordinator.last_update_success is True
        assert coordinator.history["heat"] == old_heat
        entity_ids = _entity_ids(hass, entry)
        heat = hass.states.get(entity_ids[f"{entry.entry_id}-daily-heat"])
        assert heat.state == "9.4"


async def test_cloud2_cookies_reused_and_rotated(hass: HomeAssistant) -> None:
    """Persisted cookies seed the client; a rotated session is re-persisted."""
    fake = _FakeCloud2Dachs()
    captured: dict[str, object] = {}

    def _fake_build(email, password, serial=None, cookies=None):
        captured["cookies"] = cookies
        captured["serial"] = serial
        return fake

    entry = _cloud2_entry(session_cookies={"DACHSCONNECT": "old-1"})
    entry.add_to_hass(hass)
    with patch.object(Dachs, "cloud2", _fake_build):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _wait_for_data(hass, entry)

        # The re-setup passed the persisted cookies to the device builder.
        assert captured["cookies"] == {"DACHSCONNECT": "old-1"}

        # The session rotated on the (mocked) client; the next refresh
        # persists the new cookies.
        fake_cloud2 = FakeCloud2Native()
        fake_cloud2.client.session_cookies.return_value = {"DACHSCONNECT": "new-2"}
        fake.client = fake_cloud2.client
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert entry.data["session_cookies"] == {"DACHSCONNECT": "new-2"}
