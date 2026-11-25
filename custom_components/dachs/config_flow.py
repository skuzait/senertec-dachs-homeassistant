"""Config flow for the SenerTec Dachs integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    # CONF_EMAIL,  # cloud2 only; not published yet
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.helpers import selector

from .const import (
    CONF_BASE_URL,
    CONF_CONNECTION,
    # CONF_COOKIES,  # cloud2 only; not published yet
    # CONF_NATIVE_DATAPOINTS,  # cloud2 only; not published yet
    CONF_PIN,
    CONF_PORTAL_ID,
    CONF_PORTAL_PASSWORD,
    CONF_PRODUCT_NAME,
    CONF_SCAN_INTERVAL,
    # CONF_SERIAL,  # cloud2 only; not published yet
    CONNECTION_CLOUD,
    # CONNECTION_CLOUD2,  # cloud2 only; not published yet
    CONNECTION_GLT,
    CONNECTION_LOCAL,
    CONNECTION_LOCAL_AUTO,
    CONNECTION_MODES,
    DEFAULT_GLT_PORT,
    # DEFAULT_NATIVE_DATAPOINTS,  # cloud2 only; not published yet
    DEFAULT_PORT,
    DEFAULT_USERNAME,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
    SCAN_INTERVAL_CLOUD_SECONDS,
    SCAN_INTERVAL_LOCAL_SECONDS,
)
from senertec_dachs import (
    AuthenticationError,
    # Cloud2Client,  # cloud2 not published yet
    ConnectionError as DachsConnectionError,
    Dachs,
    DachsError,
    RequestTimeoutError,
)

_LOGGER = logging.getLogger(__name__)

_INTERVAL_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=MIN_SCAN_INTERVAL_SECONDS,
        max=MAX_SCAN_INTERVAL_SECONDS,
        mode=selector.NumberSelectorMode.BOX,
    )
)

_PORT_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(min=1, max=65535, mode=selector.NumberSelectorMode.BOX)
)

_SCHEMA_LOCAL = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): _PORT_SELECTOR,
        vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
        vol.Optional(
            CONF_SCAN_INTERVAL, default=SCAN_INTERVAL_LOCAL_SECONDS
        ): _INTERVAL_SELECTOR,
    }
)

_SCHEMA_GLT = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_GLT_PORT): _PORT_SELECTOR,
        vol.Optional(CONF_PIN): str,
        vol.Optional(
            CONF_SCAN_INTERVAL, default=SCAN_INTERVAL_LOCAL_SECONDS
        ): _INTERVAL_SELECTOR,
    }
)

_SCHEMA_CLOUD = vol.Schema(
    {
        vol.Required(CONF_PORTAL_ID): str,
        vol.Required(CONF_PORTAL_PASSWORD): str,
        vol.Optional(
            CONF_SCAN_INTERVAL, default=SCAN_INTERVAL_CLOUD_SECONDS
        ): _INTERVAL_SELECTOR,
    }
)

# cloud2 not published yet
# _SCHEMA_CLOUD2 = vol.Schema(
#     {
#         vol.Required(CONF_EMAIL): str,
#         vol.Required(CONF_PASSWORD): str,
#         vol.Optional(
#             CONF_SCAN_INTERVAL, default=SCAN_INTERVAL_CLOUD_SECONDS
#         ): _INTERVAL_SELECTOR,
#         vol.Optional(
#             CONF_NATIVE_DATAPOINTS, default=DEFAULT_NATIVE_DATAPOINTS
#         ): selector.BooleanSelector(),
#     }
# )

_SCHEMA_AUTO = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
        vol.Optional(CONF_PIN): str,
        vol.Optional(
            CONF_SCAN_INTERVAL, default=SCAN_INTERVAL_LOCAL_SECONDS
        ): _INTERVAL_SELECTOR,
    }
)

_MODE_SCHEMAS = {
    CONNECTION_LOCAL: _SCHEMA_LOCAL,
    CONNECTION_GLT: _SCHEMA_GLT,
    CONNECTION_CLOUD: _SCHEMA_CLOUD,
    # CONNECTION_CLOUD2: _SCHEMA_CLOUD2,  # cloud2 not published yet
    CONNECTION_LOCAL_AUTO: _SCHEMA_AUTO,
}


class DachsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Dachs config flow: choose a connection mode, then connect."""

    VERSION = 1

    _connection: str = CONNECTION_LOCAL_AUTO
    # cloud2 not published yet — state comes back with the DachsConnect flow.
    # _cloud2_email: str = ""
    # _cloud2_password: str = ""
    # _cloud2_base_url: str | None = None
    # _cloud2_scan_interval: int = SCAN_INTERVAL_CLOUD_SECONDS
    # _cloud2_native: bool = DEFAULT_NATIVE_DATAPOINTS
    # _cloud2_cookies: dict[str, str] = {}
    # _cloud2_units: list = []
    # Set while a reauth flow updates an existing entry.
    _reauth_entry: Any = None

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Re-collect credentials for an entry whose auth started failing."""
        entry_id = self.context["entry_id"]
        self._reauth_entry = self.hass.config_entries.async_get_entry(entry_id)
        mode = entry_data[CONF_CONNECTION]
        return await getattr(self, f"async_step_{mode}")(None)

    def _finish_reauth(self, new_data: dict[str, Any]) -> ConfigFlowResult:
        """Store the fresh credentials and reload the entry."""
        entry = self._reauth_entry
        self._reauth_entry = None
        assert entry is not None
        return self.async_update_reload_and_abort(entry, data=new_data)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how to reach the Dachs."""
        if user_input is not None:
            self._connection = user_input[CONF_CONNECTION]
            return await getattr(self, f"async_step_{self._connection}")()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONNECTION, default=CONNECTION_LOCAL_AUTO
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(CONNECTION_MODES),
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            translation_key=CONF_CONNECTION,
                        )
                    )
                }
            ),
        )

    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Connect to the local MSR2 GLT interface."""
        return await self._async_step_credentials(user_input, CONNECTION_LOCAL)

    async def async_step_glt(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Connect to the local MSR3 (Gen2) Modbus TCP interface."""
        return await self._async_step_credentials(user_input, CONNECTION_GLT)

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Connect through the SenerTec Dachsportal."""
        return await self._async_step_credentials(user_input, CONNECTION_CLOUD)

    async def async_step_local_auto(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Probe the host for MSR2 HTTP, then MSR3 Modbus TCP."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._normalize_numeric_fields(user_input)
            try:
                resolved, identity = await self._detect_local(user_input)
            except _AuthDetected:
                errors["base"] = "invalid_auth"
            except (DachsConnectionError, RequestTimeoutError):
                errors["base"] = "cannot_connect"
            except DachsError as error:
                _LOGGER.warning("Unexpected Dachs error during setup: %s", error)
                errors["base"] = "unknown"
            else:
                user_input[CONF_CONNECTION] = resolved
                if identity.get("product"):
                    user_input[CONF_PRODUCT_NAME] = identity["product"]
                unique_id = self._local_unique_id(resolved, user_input)
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=_identity_title(identity, user_input[CONF_HOST]),
                    data=user_input,
                )
        return self.async_show_form(
            step_id=CONNECTION_LOCAL_AUTO,
            data_schema=_SCHEMA_AUTO,
            errors=errors,
        )

    # cloud2 not published yet — flow returns with DachsConnect.
    # async def async_step_cloud2(
    #     self, user_input: dict[str, Any] | None = None
    # ) -> ConfigFlowResult:
    #     """Log into DachsConnect and list the account's units."""
    #     errors: dict[str, str] = {}
    #     if user_input is not None:
    #         self._normalize_numeric_fields(user_input)
    #         self._cloud2_email = user_input[CONF_EMAIL]
    #         self._cloud2_password = user_input[CONF_PASSWORD]
    #         self._cloud2_base_url = user_input.get(CONF_BASE_URL)
    #         if CONF_SCAN_INTERVAL in user_input:
    #             self._cloud2_scan_interval = int(user_input[CONF_SCAN_INTERVAL])
    #         self._cloud2_native = bool(
    #             user_input.get(CONF_NATIVE_DATAPOINTS, DEFAULT_NATIVE_DATAPOINTS)
    #         )
    #         client = _cloud2_units_client(self._cloud2_email, self._cloud2_password, self._cloud2_base_url)
    #         try:
    #             self._cloud2_units = await client.units()
    #             self._cloud2_cookies = client.session_cookies()
    #         except AuthenticationError:
    #             errors["base"] = "invalid_auth"
    #         except (DachsConnectionError, RequestTimeoutError):
    #             errors["base"] = "cannot_connect"
    #         except DachsError as error:
    #             _LOGGER.warning("Unexpected Dachs error during setup: %s", error)
    #             errors["base"] = "unknown"
    #         finally:
    #             await client.close()
    #         if not errors:
    #             known_serial = (
    #                 self._reauth_entry.data.get(CONF_SERIAL)
    #                 if self._reauth_entry is not None
    #                 else None
    #             )
    #             if known_serial and any(
    #                 u.serial == known_serial for u in self._cloud2_units
    #             ):
    #                 return await self._async_create_cloud2_entry(known_serial)
    #             if len(self._cloud2_units) == 1:
    #                 return await self._async_create_cloud2_entry(
    #                     self._cloud2_units[0].serial
    #                 )
    #             if not self._cloud2_units:
    #                 errors["base"] = "no_units"
    #             else:
    #                 return await self.async_step_cloud2_device()
    #     return self.async_show_form(
    #         step_id=CONNECTION_CLOUD2,
    #         data_schema=_SCHEMA_CLOUD2,
    #         errors=errors,
    #     )

    # async def async_step_cloud2_device(
    #     self, user_input: dict[str, Any] | None = None
    # ) -> ConfigFlowResult:
    #     """Pick which unit of the account to read."""
    #     errors: dict[str, str] = {}
    #     if user_input is not None:
    #         return await self._async_create_cloud2_entry(user_input[CONF_SERIAL])
    #     options = [
    #         selector.SelectOptionDict(
    #             value=unit.serial,
    #             label=_unit_label(unit),
    #         )
    #         for unit in self._cloud2_units
    #     ]
    #     return self.async_show_form(
    #         step_id="cloud2_device",
    #         data_schema=vol.Schema(
    #             {
    #                 vol.Required(CONF_SERIAL): selector.SelectSelector(
    #                     selector.SelectSelectorConfig(
    #                         options=options,
    #                         mode=selector.SelectSelectorMode.DROPDOWN,
    #                     )
    #                 )
    #             }
    #         ),
    #         errors=errors,
    #     )

    # async def _async_create_cloud2_entry(self, serial: str) -> ConfigFlowResult:
    #     """Create the entry for the chosen DachsConnect unit."""
    #     unit = next((u for u in self._cloud2_units if u.serial == serial), None)
    #     identity_title = _identity_title(
    #         {"serial": serial, "part": unit.model if unit else None}, serial
    #     )
    #     # Mirror the account line the panel shows elsewhere: the device
    #     # plus the email it is read with.
    #     title = f"{identity_title} · {self._cloud2_email}"
    #     if self._reauth_entry is not None:
    #         cookies = self._cloud2_cookies or self._reauth_entry.data.get(CONF_COOKIES)
    #         return self._finish_reauth(
    #             {
    #                 **self._reauth_entry.data,
    #                 CONF_EMAIL: self._cloud2_email,
    #                 CONF_PASSWORD: self._cloud2_password,
    #                 **({CONF_COOKIES: cookies} if cookies else {}),
    #             }
    #         )
    #     await self.async_set_unique_id(f"cloud2:{serial}")
    #     self._abort_if_unique_id_configured()
    #     return self.async_create_entry(
    #         title=title,
    #         data={
    #             CONF_CONNECTION: CONNECTION_CLOUD2,
    #             CONF_EMAIL: self._cloud2_email,
    #             CONF_PASSWORD: self._cloud2_password,
    #             CONF_SERIAL: serial,
    #             CONF_SCAN_INTERVAL: self._cloud2_scan_interval,
    #             CONF_NATIVE_DATAPOINTS: self._cloud2_native,
    #             **({CONF_COOKIES: self._cloud2_cookies} if self._cloud2_cookies else {}),
    #             **(
    #                 {CONF_BASE_URL: self._cloud2_base_url}
    #                 if self._cloud2_base_url
    #                 else {}
    #             ),
    #             **(
    #                 {CONF_PRODUCT_NAME: unit.model}
    #                 if unit and unit.model
    #                 else {}
    #             ),
    #         },
    #     )

    async def _async_step_credentials(
        self, user_input: dict[str, Any] | None, connection: str
    ) -> ConfigFlowResult:
        """Collect and validate the credentials for the chosen mode."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._normalize_numeric_fields(user_input)
            try:
                title, unique_id = await self._validate_connection(
                    user_input, connection
                )
            except ValueError:
                errors["base"] = "invalid_host"
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (DachsConnectionError, RequestTimeoutError):
                errors["base"] = "cannot_connect"
            except DachsError as error:
                _LOGGER.warning("Unexpected Dachs error during setup: %s", error)
                errors["base"] = "unknown"
            else:
                if self._reauth_entry is not None:
                    return self._finish_reauth(
                        {**self._reauth_entry.data, **user_input}
                    )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=title,
                    data={CONF_CONNECTION: connection, **user_input},
                )
        return self.async_show_form(
            step_id=connection,
            data_schema=_MODE_SCHEMAS[connection],
            errors=errors,
        )

    @staticmethod
    def _normalize_numeric_fields(user_input: dict[str, Any]) -> None:
        """Accept "host:port" in the host field and number-box floats.

        The frontend number box also delivers numbers as floats or
        strings; the library requires ints. Bare IPv6 addresses stay
        intact.
        """
        if CONF_HOST in user_input:
            host, inline_port = _split_host_port(user_input[CONF_HOST])
            user_input[CONF_HOST] = host
            if inline_port is not None:
                user_input[CONF_PORT] = inline_port
        for numeric_key in (CONF_PORT, CONF_SCAN_INTERVAL):
            if numeric_key in user_input:
                user_input[numeric_key] = int(user_input[numeric_key])

    async def _detect_local(self, user_input: dict[str, Any]) -> tuple[str, dict]:
        """Probe MSR2 HTTP first, then MSR3 Modbus TCP.

        Returns the resolved connection constant plus the identity keys
        seen during the probe (serial number, part/model designation).
        Raises ``_AuthDetected`` when the host answers as MSR2 but
        rejects the credentials (then it is an MSR2, and the user must
        fix the password, not probe on).
        """
        msr2 = Dachs(
            user_input[CONF_HOST],
            port=int(user_input.get(CONF_PORT, DEFAULT_PORT)),
            username=user_input.get(CONF_USERNAME, DEFAULT_USERNAME),
            password=user_input.get(CONF_PASSWORD, ""),
        )
        try:
            await msr2.update()
        except AuthenticationError:
            raise _AuthDetected from None
        except (DachsConnectionError, RequestTimeoutError):
            pass  # nothing speaking MSR2 HTTP there; try Modbus
        else:
            identity = {
                "serial": msr2.serial_number,
                "part": msr2.part_number,
            }
            await msr2.close()
            return CONNECTION_LOCAL, identity
        await msr2.close()

        pin = user_input.get(CONF_PIN)
        msr3 = Dachs.glt(
            user_input[CONF_HOST],
            port=int(user_input.get(CONF_PORT, DEFAULT_GLT_PORT)),
            pin=int(pin) if pin else None,
        )
        try:
            await msr3.update()
            device_type = msr3.client.profile().device_type_name
            identity = {
                "serial": msr3.serial_number,
                "part": device_type,
                "product": device_type,
            }
        finally:
            await msr3.close()
        return CONNECTION_GLT, identity

    @staticmethod
    def _local_unique_id(resolved: str, user_input: dict[str, Any]) -> str:
        host = user_input[CONF_HOST]
        if resolved == CONNECTION_GLT:
            return f"glt:{host}:{user_input.get(CONF_PORT, DEFAULT_GLT_PORT)}"
        return f"local:{host}:{user_input.get(CONF_PORT, DEFAULT_PORT)}"

    async def _validate_connection(
        self, user_input: dict[str, Any], connection: str
    ) -> tuple[str, str]:
        """Connect once; return a friendly title and the unique id."""
        host = user_input.get(CONF_HOST)
        portal_id = user_input.get(CONF_PORTAL_ID)

        if connection == CONNECTION_LOCAL:
            device = _local_device(user_input)
        elif connection == CONNECTION_GLT:
            device = _glt_device(user_input)
        else:
            device = _cloud_device(user_input)

        try:
            await device.update()
            identity: dict = {
                "serial": device.serial_number,
                "part": device.part_number,
            }
            if connection == CONNECTION_GLT:
                # The GLT profile knows the exact device type (e.g.
                # "Dachs 5.5 (G5.5)"); capture it for the device registry.
                device_type = device.client.profile().device_type_name
                if device_type:
                    user_input[CONF_PRODUCT_NAME] = device_type
                    identity["part"] = device_type
            elif connection == CONNECTION_CLOUD:
                # The portal knows the exact product designation (e.g.
                # "HKA-G-5.5-S2.2"); the local interface does not.
                product = _product_name(await device.client.metainfo())
                if product:
                    user_input[CONF_PRODUCT_NAME] = product
                    identity["part"] = product
        finally:
            # A rejected login must not leak the client's aiohttp
            # session; every exit path closes the device.
            await device.close()

        title = _identity_title(identity, host or portal_id)
        if connection == CONNECTION_CLOUD:
            # The account the entry reads with stays visible next to
            # the device, so multiple portal accounts are distinguishable.
            title = f"{title} · {portal_id}"

        if connection == CONNECTION_LOCAL:
            return title, f"local:{host}:{user_input.get(CONF_PORT, DEFAULT_PORT)}"
        if connection == CONNECTION_GLT:
            return title, f"glt:{host}:{user_input.get(CONF_PORT, DEFAULT_GLT_PORT)}"
        return title, f"cloud:{portal_id}"


class _AuthDetected(Exception):
    """The host answered as MSR2 but rejected the credentials."""


def _local_device(user_input: dict[str, Any]) -> Dachs:
    """Build the local device for validation."""
    return Dachs(
        user_input[CONF_HOST],
        port=user_input.get(CONF_PORT, DEFAULT_PORT),
        username=user_input.get(CONF_USERNAME, DEFAULT_USERNAME),
        password=user_input.get(CONF_PASSWORD, ""),
    )


def _glt_device(user_input: dict[str, Any]) -> Dachs:
    """Build the MSR3 Modbus device for validation."""
    pin = user_input.get(CONF_PIN)
    return Dachs.glt(
        user_input[CONF_HOST],
        port=user_input.get(CONF_PORT, DEFAULT_GLT_PORT),
        pin=int(pin) if pin else None,
    )


# cloud2 not published yet
# def _cloud2_units_client(email: str, password: str, base_url: str | None) -> Cloud2Client:
#     """Build a throwaway DachsConnect client for the unit listing.
#
#     ``base_url`` is a hidden key (not in the form schema) so tests can
#     point the real client at a loopback portal.
#     """
#     if base_url:
#         return Cloud2Client(email, password, base_url=base_url)
#     return Cloud2Client(email, password)


# cloud2 not published yet
# def _unit_label(unit) -> str:
#     """Dropdown label for a DachsConnect unit: model, serial, location."""
#     parts = [unit.model or "Dachs", unit.serial]
#     if unit.location_name:
#         parts.append(unit.location_name)
#     return " — ".join(parts)


def _identity_title(identity: dict, fallback: str | None) -> str:
    """Title from the device identity, without doubling the 'Dachs' prefix."""
    serial = identity.get("serial")
    part = identity.get("part")
    model = part
    prefix = "" if (model or "").lower().startswith("dachs") else "Dachs"
    if model and serial:
        return f"{prefix} {model} ({serial})".strip()
    if serial:
        return f"Dachs {serial}"
    if model:
        return f"{prefix} {model}".strip()
    return f"Dachs {fallback}"


def _cloud_device(user_input: dict[str, Any]) -> Dachs:
    """Build the Dachsportal device for validation.

    ``base_url`` is a hidden key: never shown in the form, it exists so
    the integration tests can point the real client at a loopback
    portal instead of mocking the library.
    """
    kwargs: dict[str, Any] = {}
    if CONF_BASE_URL in user_input:
        kwargs["base_url"] = user_input[CONF_BASE_URL]
    return Dachs.cloud(user_input[CONF_PORTAL_ID], user_input[CONF_PORTAL_PASSWORD], **kwargs)


def _split_host_port(host: str) -> tuple[str, int | None]:
    """Split an optional inline ``host:port`` into host and port.

    Bare IPv6 addresses (multiple colons) are left untouched; a
    bracketed ``[v6]:port`` is split. Returns ``(host, None)`` when
    there is no port to extract.
    """
    if host.startswith("["):
        closing = host.find("]")
        if closing != -1 and host[closing + 1:].startswith(":"):
            tail = host[closing + 2:]
            if tail.isdigit():
                return host[: closing + 1], int(tail)
        return host, None
    if host.count(":") == 1:
        head, tail = host.split(":")
        if head and tail.isdigit():
            return head, int(tail)
    return host, None


def _product_name(metainfo: dict) -> str | None:
    """Extract the product designation from the portal's metainfo.

    The portal sends ``"b<portal-id>\\n<designation>"`` — e.g.
    ``"b85312\\nHKA-G-5.5-S2.2"`` — so the designation is the last
    line.
    """
    name = metainfo.get("productName")
    if not isinstance(name, str):
        return None
    lines = [line.strip() for line in name.splitlines() if line.strip()]
    return lines[-1] if lines else None
