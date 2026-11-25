"""Config-flow tests against the loopback fakes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dachs.const import DOMAIN
from senertec_dachs import AuthenticationError, Dachs

from fake_dachs import CloudPortalFake, LocalServerFake
from fake_glt import FakeGltServer


class _FakeCloud2DachsStub:
    """Absorbs the auto-setup of an entry created by a cloud2 flow."""

    def __init__(self) -> None:
        self.closed = False

    async def update(self):
        raise AuthenticationError("stub: no live DachsConnect in tests")

    async def close(self) -> None:
        self.closed = True

    def __getattr__(self, name: str):
        return None


async def test_local_flow_creates_entry(hass: HomeAssistant) -> None:
    """A working local connection creates an entry with serial in the title."""
    fake = LocalServerFake()
    await fake.start()
    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"connection": "local"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "local"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": "127.0.0.1",
                "port": fake.port,
                "username": "glt",
                "password": "",
                "scan_interval": 30,
            },
        )
        await hass.async_block_till_done()
    finally:
        await fake.stop()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dachs 4711 (0000000001)"
    assert result["data"] == {
        "connection": "local",
        "host": "127.0.0.1",
        "port": fake.port,
        "username": "glt",
        "password": "",
        "scan_interval": 30,
    }


async def test_local_flow_unreachable(hass: HomeAssistant) -> None:
    """A closed port shows the cannot-connect error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"connection": "local"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1", "port": 1}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_local_flow_normalizes_port_type(hass: HomeAssistant) -> None:
    """A float port from the frontend number box is stored as int."""
    fake = LocalServerFake()
    await fake.start()
    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"connection": "local"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "127.0.0.1", "port": float(fake.port)},
        )
        await hass.async_block_till_done()
    finally:
        await fake.stop()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["port"] == fake.port
    assert isinstance(result["data"]["port"], int)


async def test_local_flow_accepts_inline_port(hass: HomeAssistant) -> None:
    """``host:port`` in the host field overrides the default port."""
    fake = LocalServerFake()
    await fake.start()
    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"connection": "local"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": f"127.0.0.1:{fake.port}"}
        )
        await hass.async_block_till_done()
    finally:
        await fake.stop()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["host"] == "127.0.0.1"
    assert result["data"]["port"] == fake.port
    assert isinstance(result["data"]["port"], int)


async def test_glt_flow_creates_entry(hass: HomeAssistant) -> None:
    """A working MSR3 Modbus connection creates an entry with the model."""
    fake = FakeGltServer()
    await fake.start()
    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"connection": "glt"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "glt"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": "127.0.0.1",
                "port": fake.port,
                "pin": "1234",
                "scan_interval": 30,
            },
        )
        await hass.async_block_till_done()
    finally:
        await fake.stop()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dachs 5.5 (G5.5) (2110123456789ABC)"
    assert result["data"]["connection"] == "glt"
    assert result["data"]["product_name"] == "Dachs 5.5 (G5.5)"
    assert result["data"]["pin"] == "1234"


async def test_glt_flow_unreachable(hass: HomeAssistant) -> None:
    """A closed Modbus port shows the cannot-connect error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"connection": "glt"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1", "port": 1}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_auto_detect_msr2(hass: HomeAssistant) -> None:
    """The auto mode resolves to MSR2 when the HTTP interface answers."""
    fake = LocalServerFake()
    await fake.start()
    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"connection": "local_auto"}
        )
        assert result["step_id"] == "local_auto"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": f"127.0.0.1:{fake.port}",
                "username": "glt",
                "password": "",
                "scan_interval": 30,
            },
        )
        await hass.async_block_till_done()
    finally:
        await fake.stop()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dachs 4711 (0000000001)"
    assert result["data"]["connection"] == "local"
    assert result["data"]["port"] == fake.port


async def test_auto_detect_msr3(hass: HomeAssistant) -> None:
    """The auto mode falls through to Modbus TCP when HTTP finds nothing."""
    fake = FakeGltServer()
    await fake.start()
    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"connection": "local_auto"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": f"127.0.0.1:{fake.port}",
                "pin": "1234",
                "scan_interval": 30,
            },
        )
        await hass.async_block_till_done()
    finally:
        await fake.stop()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["connection"] == "glt"
    assert result["data"]["product_name"] == "Dachs 5.5 (G5.5)"
    assert result["data"]["port"] == fake.port


async def test_auto_detect_nothing_home(hass: HomeAssistant) -> None:
    """No MSR2 and no MSR3 reachable shows the cannot-connect error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"connection": "local_auto"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1:1"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


# cloud2 not published yet — flow tests return with DachsConnect.
# class _FakeCloud2Client:
#     """Stands in for Cloud2Client at the config-flow boundary."""
#
#     units_result: list = []
#     raised: Exception | None = None
#     cookies_result: dict[str, str] = {"DACHSCONNECT": "sess-1"}
#
#     def __init__(self, email: str, password: str, base_url: str | None = None) -> None:
#         self.email = email
#         self.password = password
#         self.base_url = base_url
#
#     async def units(self) -> list:
#         if _FakeCloud2Client.raised is not None:
#             raise _FakeCloud2Client.raised
#         return _FakeCloud2Client.units_result
#
#     def session_cookies(self) -> dict[str, str]:
#         return _FakeCloud2Client.cookies_result
#
#     async def close(self) -> None:
#         return None
#
#
# _UNITS = [
#     SimpleNamespace(
#         serial="96385",
#         model="Dachs 5.5",
#         location_name="Heizraum",
#     ),
#     SimpleNamespace(
#         serial="11111",
#         model="Gen2 F5.5",
#         location_name=None,
#     ),
# ]


# async def test_cloud2_flow_multi_unit_dropdown(hass: HomeAssistant) -> None:
#     """A multi-unit account gets a serial dropdown before the entry."""
#     _FakeCloud2Client.units_result = _UNITS
#     _FakeCloud2Client.raised = None
#     stub = _FakeCloud2DachsStub()
#     with (
#         patch("custom_components.dachs.config_flow.Cloud2Client", _FakeCloud2Client),
#         # The flow's created entry is set up immediately by HA; keep that
#         # setup away from the real DachsConnect endpoint.
#         patch.object(Dachs, "cloud2", lambda email, password, serial=None, cookies=None: stub),
#     ):
#         result = await hass.config_entries.flow.async_init(
#             DOMAIN, context={"source": config_entries.SOURCE_USER}
#         )
#         result = await hass.config_entries.flow.async_configure(
#             result["flow_id"], {"connection": "cloud2"}
#         )
#         assert result["type"] is FlowResultType.FORM
#         assert result["step_id"] == "cloud2"
#
#         result = await hass.config_entries.flow.async_configure(
#             result["flow_id"],
#             {
#                 "email": "you@example.com",
#                 "password": "secret",
#                 "scan_interval": 120,
#             },
#         )
#         assert result["type"] is FlowResultType.FORM
#         assert result["step_id"] == "cloud2_device"
#
#         result = await hass.config_entries.flow.async_configure(
#             result["flow_id"], {"serial": "96385"}
#         )
#         await hass.async_block_till_done()
#
#     assert result["type"] is FlowResultType.CREATE_ENTRY
#     assert result["title"] == "Dachs 5.5 (96385) · you@example.com"
#     assert result["data"]["connection"] == "cloud2"
#     assert result["data"]["serial"] == "96385"
#     assert result["data"]["product_name"] == "Dachs 5.5"
#     assert result["data"]["scan_interval"] == 120
#     assert result["data"]["native_datapoints"] is False
#     assert result["data"]["session_cookies"] == {"DACHSCONNECT": "sess-1"}


# async def test_cloud2_flow_persists_session_cookies(hass) -> None:
#     """Session cookies from the unit listing land in the entry data."""
#     _FakeCloud2Client.units_result = _UNITS
#     _FakeCloud2Client.raised = None
#     captured: dict[str, object] = {}
#     stub = _FakeCloud2DachsStub()
#
#     def _fake_build(email, password, serial=None, cookies=None):
#         captured["cookies"] = cookies
#         captured["serial"] = serial
#         return stub
#
#     with (
#         patch("custom_components.dachs.config_flow.Cloud2Client", _FakeCloud2Client),
#         patch.object(Dachs, "cloud2", _fake_build),
#     ):
#         result = await hass.config_entries.flow.async_init(
#             DOMAIN, context={"source": config_entries.SOURCE_USER}
#         )
#         result = await hass.config_entries.flow.async_configure(
#             result["flow_id"], {"connection": "cloud2"}
#         )
#         result = await hass.config_entries.flow.async_configure(
#             result["flow_id"],
#             {"email": "you@example.com", "password": "secret"},
#         )
#         assert result["type"] is FlowResultType.FORM
#         assert result["step_id"] == "cloud2_device"
#
#         result = await hass.config_entries.flow.async_configure(
#             result["flow_id"], {"serial": "96385"}
#         )
#         await hass.async_block_till_done()
#
#     assert result["type"] is FlowResultType.CREATE_ENTRY
#     assert captured["serial"] == "96385"
#     assert captured["cookies"] == {"DACHSCONNECT": "sess-1"}


# async def test_cloud2_flow_native_datapoints_round_trip(
#     hass: HomeAssistant,
# ) -> None:
#     """The native datapoints boolean survives the flow into entry data."""
#     _FakeCloud2Client.units_result = [_UNITS[1]]
#     _FakeCloud2Client.raised = None
#     stub = _FakeCloud2DachsStub()
#     with (
#         patch("custom_components.dachs.config_flow.Cloud2Client", _FakeCloud2Client),
#         patch.object(Dachs, "cloud2", lambda email, password, serial=None, cookies=None: stub),
#     ):
#         result = await hass.config_entries.flow.async_init(
#             DOMAIN, context={"source": config_entries.SOURCE_USER}
#         )
#         result = await hass.config_entries.flow.async_configure(
#             result["flow_id"], {"connection": "cloud2"}
#         )
#         result = await hass.config_entries.flow.async_configure(
#             result["flow_id"],
#             {
#                 "email": "you@example.com",
#                 "password": "secret",
#                 "scan_interval": 120,
#                 "native_datapoints": False,
#             },
#         )
#         await hass.async_block_till_done()
#
#     assert result["type"] is FlowResultType.CREATE_ENTRY
#     assert result["data"]["native_datapoints"] is False


# async def test_cloud2_flow_wrong_password(hass: HomeAssistant) -> None:
#     """A rejected DachsConnect login shows the invalid-auth error."""
#     _FakeCloud2Client.raised = AuthenticationError("bad login")
#     with patch(
#         "custom_components.dachs.config_flow.Cloud2Client", _FakeCloud2Client
#     ):
#         result = await hass.config_entries.flow.async_init(
#             DOMAIN, context={"source": config_entries.SOURCE_USER}
#         )
#         result = await hass.config_entries.flow.async_configure(
#             result["flow_id"], {"connection": "cloud2"}
#         )
#         result = await hass.config_entries.flow.async_configure(
#             result["flow_id"],
#             {"email": "you@example.com", "password": "wrong"},
#         )
#
#     assert result["type"] is FlowResultType.FORM
#     assert result["step_id"] == "cloud2"
#     assert result["errors"] == {"base": "invalid_auth"}


# async def test_cloud2_reauth_updates_entry(hass: HomeAssistant) -> None:
#     """A reauth flow refreshes the credentials of the existing entry."""
#     entry = MockConfigEntry(
#         domain=DOMAIN,
#         unique_id="cloud2:96385",
#         title="Dachs 5.5 (96385)",
#         data={
#             "connection": "cloud2",
#             "email": "old@example.com",
#             "password": "old",
#             "serial": "96385",
#         },
#     )
#     entry.add_to_hass(hass)
#     _FakeCloud2Client.units_result = _UNITS
#     _FakeCloud2Client.raised = None
#     with patch(
#         "custom_components.dachs.config_flow.Cloud2Client", _FakeCloud2Client
#     ):
#         result = await hass.config_entries.flow.async_init(
#             DOMAIN,
#             context={
#                 "source": config_entries.SOURCE_REAUTH,
#                 "entry_id": entry.entry_id,
#             },
#             data=entry.data,
#         )
#         assert result["type"] is FlowResultType.FORM
#         assert result["step_id"] == "cloud2"
#
#         result = await hass.config_entries.flow.async_configure(
#             result["flow_id"],
#             {"email": "new@example.com", "password": "newpass"},
#         )
#         await hass.async_block_till_done()
#
#     assert result["type"] is FlowResultType.ABORT
#     assert result["reason"] == "reauth_successful"
#     assert entry.data["email"] == "new@example.com"
#     assert entry.data["password"] == "newpass"
#     assert entry.data["serial"] == "96385"
#     assert entry.data["session_cookies"] == {"DACHSCONNECT": "sess-1"}


async def test_cloud_flow_creates_entry(hass: HomeAssistant) -> None:
    """A working portal login creates a cloud entry."""
    portal = CloudPortalFake()
    await portal.start()
    # base_url is a hidden test key: inject it behind the form so the
    # real client talks to the loopback portal.
    from custom_components.dachs import config_flow

    real_cloud_device = config_flow._cloud_device

    def cloud_device_with_fake(user_input: dict) -> object:
        return real_cloud_device({**user_input, "base_url": portal.url()})

    try:
        with patch.object(config_flow, "_cloud_device", cloud_device_with_fake):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"connection": "cloud"}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "portal_id": "12345",
                    "portal_password": "secret",
                    "scan_interval": 120,
                },
            )
            await hass.async_block_till_done()
    finally:
        await portal.stop()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dachs HKA-G-5.5-S2.2 (0000000001) · 12345"
    assert result["data"]["connection"] == "cloud"
    assert result["data"]["portal_id"] == "12345"
    assert result["data"]["product_name"] == "HKA-G-5.5-S2.2"
    assert result["data"]["scan_interval"] == 120


async def test_cloud_flow_wrong_password(hass: HomeAssistant) -> None:
    """A rejected portal login shows the invalid-auth error."""
    portal = CloudPortalFake(password="secret")
    await portal.start()
    from custom_components.dachs import config_flow

    real_cloud_device = config_flow._cloud_device

    def cloud_device_with_fake(user_input: dict) -> object:
        return real_cloud_device({**user_input, "base_url": portal.url()})

    try:
        with patch.object(config_flow, "_cloud_device", cloud_device_with_fake):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"connection": "cloud"}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "portal_id": "12345",
                    "portal_password": "wrong",
                },
            )
    finally:
        await portal.stop()

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_duplicate_is_aborted(hass: HomeAssistant) -> None:
    """The same local target cannot be configured twice."""
    fake = LocalServerFake()
    await fake.start()
    try:
        for _ in range(2):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"connection": "local"}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"host": "127.0.0.1", "port": fake.port}
            )
            await hass.async_block_till_done()
    finally:
        await fake.stop()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
