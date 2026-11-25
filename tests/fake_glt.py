"""A fake Dachs Gen2 GLT (MSR3) Modbus TCP server for the integration tests.

Serves the register space of spec ``8098.119.000.02``: FC 0x04 answers
from a register map, FC 0x06 echoes and records. Ported from the
library's own loopback fixture (py/tests/test_glt_client.py).
"""

from __future__ import annotations

import asyncio
import struct

_HEADER = struct.Struct(">HHHB")


def _serial_words(serial: str) -> list[int]:
    raw = serial.encode("utf-8")[:20].ljust(20, b"\x00")
    return [(raw[i] << 8) | raw[i + 1] for i in range(0, 20, 2)]


def _u32(value: int) -> tuple[int, int]:
    return ((value >> 16) & 0xFFFF, value & 0xFFFF)


def _fixture_registers() -> dict[int, int]:
    """A consistent full fixture consistent with the spec tables."""
    regs: dict[int, int] = {}
    # identity
    regs[8000] = (2 << 8) | 4
    regs[8001] = (26 << 8) | 1
    words = _serial_words("2110123456789ABC")
    for offset, value in enumerate(words):
        regs[8002 + offset] = value
    regs[8012] = 5500
    # status
    regs[8013] = 2  # Läuft
    regs[8014] = 55  # 5.5 kW
    regs[8015] = 3  # Stromanforderung
    regs[8016] = 3  # 3.1 h
    regs[8017] = 3  # Fehler
    regs[8018] = 1  # pump Ein
    regs[8019] = 505  # 50.5 °C outlet
    regs[8020] = 448  # 44.8 °C inlet
    # configuration
    regs[8021] = 2
    regs[8022] = 30
    regs[8023] = 900
    regs[8024] = 1
    regs[8025] = 2
    regs[8026] = 1
    # operating data
    hi, lo = _u32(12657)
    regs[8027], regs[8028] = hi, lo
    hi, lo = _u32(4864)
    regs[8029], regs[8030] = hi, lo
    hi, lo = _u32(4300763)  # 430076.3 kWh
    regs[8031], regs[8032] = hi, lo
    hi, lo = _u32(10557500)  # 1055750.0 kWh
    regs[8033], regs[8034] = hi, lo
    hi, lo = _u32(1500)
    regs[8035], regs[8036] = hi, lo
    hi, lo = _u32(3000)
    regs[8037], regs[8038] = hi, lo
    hi, lo = _u32(8157)
    regs[8039], regs[8040] = hi, lo
    # system data
    regs[8041] = 228  # 22.8 °C outdoor
    regs[8042] = 450  # buffer T1 45.0
    regs[8043] = 600  # 60.0
    regs[8044] = 312  # 31.2
    regs[8045] = 250  # 25.0
    for address in range(8046, 8052):
        regs[address] = 0
    for offset, value in zip(range(8052, 8056), (150, 160, 170, 180)):
        regs[offset] = value  # 15.0/16.0/17.0/18.0 °C (F5..F8)
    regs[8056] = 40
    # plant configuration
    regs[8057] = 1
    regs[8058] = 500
    regs[8059] = 2
    regs[8060], regs[8061], regs[8062], regs[8063] = 25, 60, 95, 130
    regs[8064] = 2
    regs[8065] = 1
    # multi-module
    regs[8066] = 55
    regs[8067], regs[8068], regs[8069], regs[8070], regs[8071] = 1, 1, 0, 1, 1
    regs[8072] = 55
    # second heat generator
    regs[8073] = 0
    regs[8074] = 0
    hi, lo = _u32(100)
    regs[8075], regs[8076] = hi, lo
    hi, lo = _u32(450)
    regs[8077], regs[8078] = hi, lo
    regs[8079], regs[8080] = 1, 0
    regs[8081] = 240
    regs[8082] = 30
    regs[8083] = 1
    return regs


class FakeGltServer:
    """Modbus TCP loopback with the documented function codes."""

    def __init__(self) -> None:
        self.registers = _fixture_registers()
        self.written: dict[int, list[int]] = {}
        self._server: asyncio.AbstractServer | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self.host = "127.0.0.1"
        self.port = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            # Drop open client connections: Python 3.12+ wait_closed()
            # waits for the connection handlers, and an idle Modbus
            # client (open socket, no request in flight) would hang it.
            for writer in list(self._writers):
                writer.transport.abort()
            await self._server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writers.add(writer)
        try:
            while True:
                head = await reader.readexactly(_HEADER.size)
                transaction, proto, length, unit_id = _HEADER.unpack(head)
                if proto != 0:
                    # Not Modbus (e.g. an HTTP probe hitting this port);
                    # drop the connection so the prober moves on.
                    break
                body = await reader.readexactly(length - 1)
                function_code = body[0]
                payload = body[1:]
                if function_code == 0x04:
                    address, quantity = struct.unpack(">HH", payload[:4])
                    words = [
                        self.registers.get(address + index, 0)
                        for index in range(quantity)
                    ]
                    byte_count = len(words) * 2
                    answer_pdu = struct.pack(">BB", 0x04, byte_count)
                    for value in words:
                        answer_pdu += struct.pack(">H", value)
                    writer.write(
                        _HEADER.pack(transaction, 0, len(answer_pdu) + 1, unit_id)
                        + answer_pdu
                    )
                    await writer.drain()
                    continue
                if function_code == 0x06:
                    address, value = struct.unpack(">HH", payload[:4])
                    self.written.setdefault(address, []).append(value)
                    self.registers[address] = value
                    writer.write(
                        _HEADER.pack(transaction, 0, len(body) + 1, unit_id) + body
                    )
                    await writer.drain()
                    continue
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            self._writers.discard(writer)
