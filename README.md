# SenerTec Dachs for Home Assistant

Integrate your SenerTec Dachs combined heat and power (CHP) unit with Home
Assistant — read live operating data, track energies, and request runs or
power demand.

Works through the [senertec-dachs](https://github.com/skuzait/senertec-dachs)
Python library.

[![Open your Home Assistant instance and open this repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=skuzait&repository=senertec-dachs-homeassistant&category=integration)

## How it connects

Four connection modes, chosen during setup:

| Mode | What it does | Needs |
|---|---|---|
| **Local (auto-detect)** | Probes the unit automatically: MSR2 HTTP (port 8080) first, then MSR3 / Gen2 Modbus TCP (port 502), and configures whichever answers. | The Dachs' IP address; credentials optional (MSR2 GLT password and/or MSR3 GLT PIN, used only if that backend is detected) |
| **Local MSR2** | Talks to the MSR2 GLT interface on your LAN (HTTP, port 8080). Live values. | The Dachs' IP address; the GLT password (default account `glt`) |
| **Local MSR3 / Gen2 (experimental)** | Talks to the GLT interface of a Dachs Gen2 (MSR3 controller, Modbus TCP, port 502). Reads need no PIN; an optional PIN (parameter NP222) only unlocks writes on the controller. Readings are the subset the GLT register map provides: identity (serial), power, energies, runtimes, starts, and the main temperatures. **Experimental:** developed against the GLT register-map documentation and not yet verified against a real Gen2 unit — if you own one, feedback is welcome. | The Dachs' IP address; optionally the GLT PIN |
| **Cloud (old Dachsportal)** | Talks to the Dachsportal — the backend of the official DachsApp. Works from anywhere; values are the portal's cached polls (a few minutes old), and a `device_online` binary sensor shows whether the portal can currently reach your unit. | Portal ID (trailing part of the serial number) and DachsApp password |

A fifth mode, **Cloud (new DachsConnect / DachsPortal2)**, is in
development and **not yet available** — the setup flow does not offer it.

The poll interval defaults to 30 s (local modes) or 120 s (cloud modes) and
is configurable in the flow.

Setup is **non-blocking**: the device appears in Home Assistant as soon
as the connection mode is configured (the serial number and name are
known at flow time), while the first data refresh runs in the
background — the entities show up instantly and their states populate
as soon as the unit has answered.

## Installation

<!-- ha-marketplace:exclude-start -->
### Marketplace (Home Assistant 2026.11+) or HACS (2026.10 and older)

Use the badge above, or add the repository manually:

1. ⋮ menu → *Custom repositories*
2. URL: `https://github.com/skuzait/senertec-dachs-homeassistant`, category
   **Integration**
3. Install **SenerTec Dachs**

### Manual

Copy the contents of `custom_components/dachs/` into
`<config>/custom_components/dachs/` on your Home Assistant instance and
restart.
<!-- ha-marketplace:exclude-end -->

Then: **Settings → Devices & Services → Add Integration → SenerTec Dachs**,
pick a connection mode, and enter your credentials. The `senertec-dachs`
library installs automatically from PyPI.

## What you get

**Sensors**

- Power (W), electrical/thermal/condenser energy (kWh, yearly totals reset
  on 1 Jan also available)
- Runtime (total and per-start, hours), starts, engine speed
- Temperatures: outdoor, supply, return, hot water, exhaust, engine, and
  more — `unknown` when a sensor isn't connected to the unit, never a
  guessed value
- Maintenance: due flag, interval, last service
- Commissioning date, fault/warning codes (diagnostic)
- Second heat generator (SEplus): status, starts, runtime

The full list above is what MSR2 local and old Dachsportal provide. The
experimental MSR3 (Gen2) backend exposes the subset that interface
provides (identity, power, energies, runtimes, starts, main temperatures);
readings a backend cannot provide get no entity at all instead of an
`unknown` placeholder.

**Binary sensors**

- Running, maintenance due, device reachable (cloud modes)

**Controls** (MSR2 local and old Dachsportal modes only)

- *Request run* button — the same one-shot demand as the DachsApp button
- *Power demand (modules)* number — external power demand, 0–10 modules,
  valid for ten minutes per request

The experimental MSR3 (Gen2) backend is read-only here: the GLT
interface uses a watt setpoint instead of module counts, so no control
entities are created for it.

Fault and warning codes are the raw controller codes: the displayed code is
value + 100 (faults) or + 600 (warnings), 0 means none.

### Native datapoints (cloud v2)

DachsConnect (cloud2) is not limited to the documented catalogue above:
the portal knows thousands of CanIP datapoints of the unit. The
**Native datapoints (cloud v2)** option (off by default; enable it in
the cloud2 setup step) adds a **curated selection** of them as sensors
and keeps them current:

- The integration runs a live listener against the DachsConnect
  connection; every value the unit sends is checked by the
  `senertec-dachs` library's display filter, and only **admitted**
  values become entities — readings arrive as the unit answers, not
  only at the next coordinator poll (which still feeds the documented
  sensors above).
- The default filter exposes what a dashboard actually wants:
  measurements with the portal's SI-style units (temperatures, power,
  energy, voltage, current, frequency, pressure, … as far as Home
  Assistant understands them), **translated engine states**
  (`Standby`, `Started`, …) as simple sensors, and large epoch
  timestamps converted to proper **timestamp** sensors (`Date last
  maintenance`, …).
- Duplicates from other subsystems are **kept, not hidden**: when the
  same datapoint exists on several controller boards (CU-CHP01 and the
  EM/INV/WR boards), the first-seen board keeps the portal's plain
  name and the others get their own entity with a board prefix
  (`EM Actual level system`, `INV Requested Level`). Log-style datapoint
  arrays (running history rows with the same name) collapse to the
  **current element** under its plain name; portal names that already
  carry the position (`Temperature sensor 6`, `Voltage phase L2`) keep
  all their elements untouched.
- Everything that would only clutter a dashboard is never admitted:
  free-form text and portal debug strings, unit-less counters
  (`Number of entries`, `Conf. table version`), money datapoints,
  sensor sentinels (-327.68 °C = "sensor not connected"), and
  datapoints the unit never sends — a unit without a battery will
  never show battery sensors.
- Names and units are the **portal's own** — the same German/English
  labels and unit strings you see on the DachsConnect app.
- Entities are created **lazily**: a datapoint only gets an entity when
  its first real value arrives, named by the portal and identified by
  the datapoint id (array datapoints carry their element index).
- Expect roughly a few hundred curated sensors on a typical Dachs
  Gen2, not thousands. If you only need the documented catalogue,
  switch the option off; the listener is then never started.

The library exposes **everything unfiltered** for power users (full
`read_datapoints()`), so new datapoints can always be surfaced later if
the curated default misses something. Note that switching integration
versions may leave old native entities orphaned in your registry until
the integration is deleted and re-added (Home Assistant keeps unknown
entities).

### Daily energy and history (cloud v2)

DachsConnect also offers the portal's own per-day cards; the
integration turns them into Home Assistant entities on cloud2:

- **Electric energy today**: produced (self-consumed + grid feed-in),
  self consumption, grid feed-in, grid import and grid export —
  today's running totals in kWh from the portal's chart endpoints.
- **Produced heat today** and **operating hours / starts today**
  (kWh / h / count, running totals of the current day).
- **Last shutdown reason** (diagnostic): the newest informative
  shutdown reason of today from the hourly state/reason log; the
  last ~50 samples are in the entity's `samples` attribute
  (ISO timestamp → reason). Hourly "No demand" rows are skipped for
  the value itself.
- **Warning pending** (binary, diagnostic): the portal's own unit
  banner — on when the unit currently reports any warning.

These cards come from the portal's chart endpoints and refresh with
the regular cloud2 poll; a failing chart keeps its previous value
without disturbing the rest. Switching integration versions may leave
orphaned daily entities in the registry until the integration is
re-added.

## Notes and limitations

- The old cloud mode uses the Dachsportal's app API and the new cloud mode
  uses DachsConnect. Neither is an **official public API** — a SenerTec
  server change can break them at any time. Local modes are the stable
  path.
- The portals serve cached polls, not live values; check `device online`
  and the `data fetched at` diagnostic sensor before trusting cloud
  readings in automations.
- The MSR3 GLT interface is plain Modbus TCP without encryption. The
  manual advises keeping it on the local network; do not expose port 502
  to the internet.
- The MSR3 (Gen2) mode is **experimental**: it was built from the GLT
  register-map documentation and still needs testing against a real
  Dachs Gen2 unit. Expect rough edges until then.
- Local mode (MSR2) is plain HTTP without encryption. If your home network
  has untrusted devices, put the Dachs on its own network segment.
- Writes (run/power demand) are never retried automatically. If the
  outcome is uncertain, the integration reports an error rather than
  risking a duplicate command.

## License

MIT, same as the
[senertec-dachs](https://github.com/skuzait/senertec-dachs) library this
integration is built on.
