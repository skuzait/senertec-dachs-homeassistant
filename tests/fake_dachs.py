"""Loopback fakes for the MSR2 GLT interface and the Dachsportal.

These serve the exact wire formats the vendored senertec-dachs library
expects, so the integration is exercised end to end over real HTTP.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from unittest.mock import MagicMock

from aiohttp import web

# cloud2 exports are unpublished; import from the subpackage.
from senertec_dachs.cloud2 import Cloud2Client
from senertec_dachs.cloud2 import (
    DailyElectric,
    DailyHeat,
    DailyRun,
    ShutdownSample,
    UnitDetails,
)


class FakeCloud2Native:
    """Stand-in for the cloud2 native-listener path.

    ``client`` is a ``MagicMock(spec=Cloud2Client)`` so the
    integration's ``isinstance(client, Cloud2Client)`` check passes and
    the listener calls are recorded like on the real client. Tests
    deliver CanIpValue frames through :meth:`deliver`, which expects
    the listener to have been started. The daily-history methods
    return canned rows (one closed day + one running today), the
    unit snapshot carries one active warning.
    """

    def __init__(self) -> None:
        self.client = MagicMock(spec=Cloud2Client)
        self.client.session_cookies.return_value = {}
        canned = canned_cloud2_history()
        self.client.daily_electric.return_value = canned["electric"]
        self.client.daily_heat.return_value = canned["heat"]
        self.client.daily_run.return_value = canned["run"]
        self.client.shutdown_history.return_value = canned["shutdown"]
        self.client.unit_details.return_value = self.unit_details = UnitDetails(
            serial="96385",
            model="Dachs Gen2 F5.5",
            product_group="dachsII",
            article_number="8098.119.000.02",
            commissioning_date=None,
            operator_name="Skuza",
            location_name="Heizraum",
            address=None,
            postal_code=None,
            city=None,
            country_code=49,
            contact_name=None,
            phone=None,
            lead_unit_serial=None,
            module_number=2,
            has_service_contract=None,
            warnings=("Warnung: Fühler prüfen",),
            connected=True,
            online=True,
        )

    @property
    def on_value(self):
        """The callback the integration registered with start_listener."""
        start = self.client.start_listener
        if not start.called:
            raise AssertionError("start_listener was not called")
        return start.call_args.args[0]

    def deliver(self, value) -> None:
        """Push one CanIpValue through the registered listener callback."""
        self.on_value(value)


def canned_cloud2_history() -> dict[str, list]:
    """One closed day plus today's running totals, in UTC.

    Deterministic times relative to today so the daily sensors see
    "today" rows whatever day the suite runs on.
    """
    now = datetime.now(timezone.utc)
    today = now.date()
    yesterday = today - timedelta(days=1)
    at = (
        lambda day, hh, mm: datetime.combine(
            day, datetime.min.time(), tzinfo=timezone.utc
        ).replace(hour=hh, minute=mm)
    )
    return {
        "electric": [
            DailyElectric(
                day=yesterday,
                self_consumed_kwh=Decimal("12.3"),
                total_consumed_kwh=Decimal("20.4"),
                fed_in_kwh=Decimal("1.2"),
                from_grid_kwh=Decimal("7.0"),
                to_grid_kwh=Decimal("0.5"),
            ),
            DailyElectric(
                day=today,
                self_consumed_kwh=Decimal("3.1"),
                total_consumed_kwh=Decimal("5.2"),
                fed_in_kwh=Decimal("0.4"),
                from_grid_kwh=Decimal("1.7"),
                to_grid_kwh=Decimal("0.1"),
            ),
        ],
        "heat": [
            DailyHeat(day=yesterday, produced_kwh=Decimal("45.6")),
            DailyHeat(day=today, produced_kwh=Decimal("9.4")),
        ],
        "run": [
            DailyRun(
                day=yesterday,
                hours=Decimal("13.2"),
                starts=12,
                ls2_hours=Decimal("4.0"),
                ls3_hours=Decimal("9.2"),
            ),
            DailyRun(
                day=today,
                hours=Decimal("2.5"),
                starts=3,
                ls2_hours=Decimal("0.6"),
                ls3_hours=Decimal("1.9"),
            ),
        ],
        "shutdown": [
            ShutdownSample(
                at=at(yesterday, 12, 0), state="Running", reason="No demand"
            ),
            ShutdownSample(at=at(today, 7, 0), state="Running", reason="No demand"),
            ShutdownSample(
                at=at(today, 8, 30), state="Standby", reason="Heat demand satisfied"
            ),
        ],
    }

AUTH_HEADER = "Basic " + base64.b64encode(b"glt:").decode()

DEFAULT_LOCAL_VALUES: dict[str, str] = {
    "Hka_Bd_Stat.uchSeriennummer": "0000000001",
    "Hka_Bd_Stat.uchTeilenummer": "4711",
    "Hka_Bd_Stat.ulInbetriebnahmedatum": "362800800",
    "Hka_Bd.ulBetriebssekunden": "77888.39",
    "Hka_Bd.ulArbeitElektr": "429853.864",
    "Hka_Bd.ulArbeitThermHka": "983065.75",
    "Hka_Bd.ulArbeitThermKon": "72130.273",
    "Hka_Bd.ulAnzahlStarts": "24989",
    "Hka_Bd.Anforderung.ModulAnzahl": "2",
    "Hka_Bd.Anforderung.UStromF_Anf.bFlagSF": "0",
    "Hka_Bd.UStromF_Frei.bFreigabe": "254",
    "Hka_Bd.bStoerung": "0",
    "Hka_Bd.bWarnung": "0",
    "Hka_Bd.UHka_Anf.Anforderung.fStrom": "false",
    "Hka_Bd.UHka_Anf.usAnforderung": "2",
    "Hka_Bd.UHka_Frei.usFreigabe": "65535",
    "Hka_Mw1.sWirkleistung": "5.522",
    "Hka_Mw1.usDrehzahl": "2454",
    "Hka_Mw1.ulMotorlaufsekunden": "4.987",
    "Hka_Mw1.Temp.sAbgasHKA": "60",
    "Hka_Mw1.Temp.sAbgasMotor": "70",
    "Hka_Mw1.Temp.sKapsel": "35",
    "Hka_Mw1.Temp.sbAussen": "9",
    "Hka_Mw1.Temp.sbFreigabeModul": "40",
    "Hka_Mw1.Temp.sbFuehler1": "12",
    "Hka_Mw1.Temp.sbFuehler2": "13",
    "Hka_Mw1.Temp.sbGen": "75",
    "Hka_Mw1.Temp.sbMotor": "80",
    "Hka_Mw1.Temp.sbRegler": "30",
    "Hka_Mw1.Temp.sbRuecklauf": "56",
    "Hka_Mw1.Temp.sbVorlauf": "85",
    "Hka_Mw1.Temp.sbZS_Fuehler3": "127",
    "Hka_Mw1.Temp.sbZS_Fuehler4": "127",
    "Hka_Mw1.Temp.sbZS_Vorlauf1": "70",
    "Hka_Mw1.Temp.sbZS_Vorlauf2": "127",
    "Hka_Mw1.Temp.sbZS_Warmwasser": "52",
    "Hka_Mw1.Solltemp.sbRuecklauf": "55",
    "Hka_Mw1.Solltemp.sbVorlauf": "70",
    "Mm[0].ModulSteuerung.fModulLaeuft": "true",
    "Mm[0].ModulSteuerung.fModulVerfuegbar": "true",
    "Brenner_Bd.bIstStatus": "0",
    "Brenner_Bd.bWarnung": "0",
    "Brenner_Bd.UBrenner_Anf.usAnforderung": "0",
    "Brenner_Bd.UBrenner_Frei.bFreigabe": "254",
    "Brenner_Bd.ulAnzahlStarts": "53974",
    "Brenner_Bd.ulBetriebssekunden": "10035.062",
    "Wartung_Cache.fStehtAn": "false",
    "Wartung_Cache.ulBetriebssekundenBei": "75818.57",
    "Wartung_Cache.ulZeitstempel": "362800800",
    "Wartung_Cache.usIntervall": "3500",
}

DEFAULT_CLOUD_VALUES: dict[str, Any] = {
    "Hka_Bd_Stat.uchSeriennummer@1": "0000000001",
    "Hka_Bd.ulBetriebssekunden@1": 77888.39,
    "Hka_Bd.ulArbeitElektr@1": 429853.864,
    "Hka_Bd.ulArbeitThermHka@1": 983065.75,
    "Hka_Bd.ulArbeitThermKon@1": 72130.273,
    "Hka_Bd.ulAnzahlStarts@1": 24989,
    "Hka_Mw1.sWirkleistung@1": 5.522,
    "Hka_Mw1.usDrehzahl@1": 2454,
    "Hka_Mw1.Temp.sbAussen@1": 9,
    "Hka_Mw1.Temp.sbVorlauf@1": 85,
    "Mm[0].ModulSteuerung.fModulLaeuft@1": True,
    "Wartung_Cache.fStehtAn@1": False,
    "Hka_Bd.bStoerung@1": 0,
    "Hka_Bd.bWarnung@1": 0,
    "Hka_Bd.Anforderung.ModulAnzahl@1": 2,
}


class LocalServerFake:
    """A fake MSR2 GLT interface on 127.0.0.1 with an OS-assigned port."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(DEFAULT_LOCAL_VALUES if values is None else values)
        #: Set to e.g. 500 to make /getKey answer with that status.
        self.get_status: int = 200
        self.posts: list[dict[str, str]] = []
        self._runner: web.AppRunner | None = None
        self.port: int = 0

    async def start(self) -> int:
        """Start the fake server; returns the port."""
        app = web.Application()
        app.router.add_get("/getKey", self._get)
        app.router.add_post("/setKeys", self._set)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = self._runner.addresses[0][1]
        return self.port

    async def stop(self) -> None:
        """Stop the fake server."""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _get(self, request: web.Request) -> web.Response:
        assert request.headers["Authorization"] == AUTH_HEADER
        if self.get_status != 200:
            return web.Response(status=self.get_status)
        requested = request.query.getall("k")
        rows = [f"{key}={self.values[key]}" for key in reversed(requested) if key in self.values]
        return web.Response(text="\r\n".join(rows) + "\r\n")

    async def _set(self, request: web.Request) -> web.Response:
        assert request.headers["Authorization"] == AUTH_HEADER
        assert request.content_type == "application/x-www-form-urlencoded"
        fields = dict(await request.post())
        self.posts.append(fields)
        return web.Response(text="\n".join(f"{key} ok" for key in fields))


class CloudPortalFake:
    """A fake Dachsportal: checkLogin session, metainfoLong, get/set, run."""

    def __init__(
        self,
        values: dict[str, Any] | None = None,
        password: str = "secret",
        device_offline: bool = False,
    ) -> None:
        self.values = dict(DEFAULT_CLOUD_VALUES if values is None else values)
        self.password = password
        self.device_offline = device_offline
        #: Set to e.g. 500 to make metainfoLong answer with that status.
        self.metainfo_status: int = 200
        self.requests: list[tuple[str, dict[str, str]]] = []
        self._valid_tokens: set[str] = set()
        self._runner: web.AppRunner | None = None
        self.port: int = 0

    async def start(self) -> int:
        """Start the fake portal; returns the port."""
        app = web.Application()
        app.router.add_post("/dachsportal-app2/msrData/checkLogin", self._check_login)
        app.router.add_post("/dachsportal-app2/msrData/metainfoLong", self._metainfo)
        app.router.add_post("/dachsportal-app2/msrData/get", self._get)
        app.router.add_post("/dachsportal-app2/msrData/set", self._set)
        app.router.add_post("/dachsportal-app2/msrData/dachsAnfordern", self._anfordern)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = self._runner.addresses[0][1]
        return self.port

    async def stop(self) -> None:
        """Stop the fake portal."""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    def url(self) -> str:
        """Base URL the cloud client should use."""
        return f"http://127.0.0.1:{self.port}/dachsportal-app2/msrData"

    async def _fields(self, request: web.Request) -> dict[str, str]:
        fields = dict(await request.post())
        return fields

    def _guarded(self, fields: dict[str, str]) -> bool:
        return fields.get("token") in self._valid_tokens

    async def _check_login(self, request: web.Request) -> web.Response:
        fields = await self._fields(request)
        self.requests.append(("checkLogin", fields))
        if fields.get("passwd") != self.password:
            # A failed login invalidates the current session server-side.
            self._valid_tokens.clear()
            response = web.json_response(
                {"loginOk": False, "message": "Logindaten inkorrekt!"}
            )
        else:
            token = f"token-{len(self._valid_tokens) + 1}"
            self._valid_tokens.add(token)
            response = web.json_response(
                {"loginOk": True, "token": token, "datenschutz": True}
            )
        response.set_cookie("JSESSIONID", "session-1")
        return response

    async def _metainfo(self, request: web.Request) -> web.Response:
        fields = await self._fields(request)
        self.requests.append(("metainfoLong", fields))
        if self.metainfo_status != 200:
            return web.json_response(
                {"error": "internal"}, status=self.metainfo_status
            )
        if not self._guarded(fields):
            return web.json_response(
                {"success": False, "relogin": True}, status=401
            )
        return web.json_response(
            {
                "offline": self.device_offline,
                "fetchedAt": int(time.time() * 1000),
                "module": ["L1"],
                "productName": "b12345\nHKA-G-5.5-S2.2",
                "type": "ethernet",
            }
        )

    async def _get(self, request: web.Request) -> web.Response:
        fields = await self._fields(request)
        self.requests.append(("get", fields))
        if not self._guarded(fields):
            return web.json_response(
                {"success": False, "relogin": True}, status=401
            )
        # The real portal answers with a flat mapping of the requested
        # keys plus the app.* block; unrequested keys would be a
        # protocol violation the client rejects.
        out: dict[str, Any] = {"app.revision": "v2.0.0-265"}
        for entry in json.loads(fields["keys"]):
            key = entry["key"]
            if key in self.values:
                out[key] = self.values[key]
        return web.json_response(out)

    async def _set(self, request: web.Request) -> web.Response:
        fields = await self._fields(request)
        self.requests.append(("set", fields))
        if not self._guarded(fields):
            return web.json_response(
                {"success": False, "relogin": True}, status=401
            )
        return web.json_response({"ok": True})

    async def _anfordern(self, request: web.Request) -> web.Response:
        fields = await self._fields(request)
        self.requests.append(("dachsAnfordern", fields))
        if not self._guarded(fields):
            return web.json_response(
                {"success": False, "relogin": True}, status=401
            )
        return web.json_response({"ok": True, "message": "Laufanforderung abgesetzt!"})
