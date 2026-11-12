# AERO-HUB — Smart Air Quality Monitoring

AERO-HUB is a full-stack IoT air-quality dashboard. It supports two deployment
modes with the same React frontend and the same FastAPI REST/WebSocket API:

| Mode | Data path | Use it when |
|---|---|---|
| **1. Direct (Raspberry Pi)** | Pi runs the API + sensor loop → WebSocket/REST → browser on the LAN | the Pi is physically with you |
| **2. Cloud (MongoDB Atlas)** | Pi → FastAPI → MongoDB Atlas → change stream → WebSocket → browser | you want remote access and durable history |

> **Measurement note:** the “Project air-quality score” is a project indicator,
> not a regulatory AQI or health assessment. MQ-7/MQ-135 and optical dust sensors
> require warm-up, reference measurements and calibration. Uncalibrated
> concentrations are never invented by the Pi client.

## Architecture

### Mode 2 — Cloud + MongoDB (recommended for history and remote access)

```text
┌──────────────────┐   HTTP POST    ┌──────────────────┐   insert   ┌──────────────────┐
│ Raspberry Pi     │ ─────────────► │ FastAPI backend  │ ─────────► │ MongoDB Atlas    │
│ raspberry_pi.py  │                │ (this repo)      │            │ free cluster     │
└──────────────────┘                │                  │ ◄───────── │ change stream    │
                                    │  REST + WS       │  realtime  └──────────────────┘
                                    └────────┬─────────┘
                                             │ WebSocket + REST
                                             ▼
                                    ┌──────────────────┐
                                    │ React dashboard  │
                                    └──────────────────┘
```

The browser never receives MongoDB credentials. The backend is the only
component that talks to Atlas. The backend watches the `readings` collection
with a **change stream**, so it can broadcast readings inserted by any writer —
including a second backend instance or an optional direct database writer.

### Mode 1 — Raspberry Pi direct (LAN only)

```text
┌─────────────────────────────────────────────┐
│ Raspberry Pi                                │
│  FastAPI backend (file store)               │
│  sensor loop: MQ-7, MQ-135, dust, BMP280    │
│  REST + WebSocket on port 8000              │
└───────────────────┬─────────────────────────┘
                    │ WebSocket + REST over the LAN
                    ▼
          ┌─────────────────────┐
          │ React dashboard     │
          └─────────────────────┘
```

A browser cannot listen for WebSocket connections, so in direct mode the Pi
runs the small FastAPI server and the browser connects to it. Data is persisted
to `backend/data/airsense.jsonl`, so history survives a restart. No internet or
MongoDB account is needed. The newest `FILE_MAX_READINGS` samples are kept in
RAM; the JSONL file itself keeps growing until you archive or delete it.

## Is MongoDB’s realtime feature free?

Yes, with a clarification:

- **MongoDB Atlas free tier** (formerly `M0`) is free forever: 512 MB storage,
  100 ops/sec, 500 connections, 10 GB in/out per rolling 7 days.
- **Change streams** work on the free tier because every Atlas cluster is a
  3-node replica set. That is how AERO-HUB gets realtime inserts.
- **Atlas Device Sync / App Services** — the old “realtime sync database”
  product — was **retired on 30 September 2025**. This project does not use it.

So the feature you described is available for free; it is implemented as
**Atlas + change stream + backend WebSocket**, which is also safer than exposing
the database directly to the browser.

Detailed setup: [`docs/MONGODB_SETUP.md`](docs/MONGODB_SETUP.md).

## Project layout

```text
AirDetection/
├── backend/
│   ├── app/
│   │   ├── config.py       # DATA_MODE, storage and sensor configuration
│   │   ├── store.py        # MongoDB / JSONL / memory storage backends
│   │   ├── services.py     # ingestion, alerts, scoring, area assessment
│   │   ├── routes.py       # REST API
│   │   ├── hardware.py     # direct-mode MCP3008/MQ/BMP280 reader
│   │   ├── check_mongo.py  # connection + index verification
│   │   └── main.py         # FastAPI app, demo loop, change-stream watcher
│   ├── .env.example        # every backend option
│   └── requirements.txt
├── frontend/
│   ├── src/services/api.js # VITE_API_URL / VITE_WS_URL / VITE_DATA_MODE
│   └── .env.example
├── raspberry_pi/
│   ├── raspberry_pi.py     # cloud-mode sensor client (HTTP POST)
│   └── .env.example
└── docs/MONGODB_SETUP.md
```

## Requirements

- Python 3.10+ and Node.js 18+ (Node 20 LTS recommended).
- A MongoDB Atlas account for mode 2. No account is needed for mode 1.
- Hardware: Raspberry Pi 3B/4, BMP280, MQ-7, MQ-135, Sharp GP2Y101AU0F, and an
  MCP3008 ADC for the analog sensors.

## Mode 2 — Cloud + MongoDB quick start

### 1. Create the free Atlas cluster

Follow [`docs/MONGODB_SETUP.md`](docs/MONGODB_SETUP.md). You need the
`mongodb+srv://…` connection string at the end.

### 2. Configure and start the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
```

Edit `backend/.env`:

```dotenv
DATA_MODE=cloud
STORAGE_BACKEND=mongodb
MONGODB_URI=mongodb+srv://aerohub:YOUR_PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority&appName=aero-hub
MONGODB_DB=airsense
MONGODB_CHANGE_STREAM=true
FRONTEND_ORIGINS=http://localhost:5173
```

Verify Atlas, then start the API:

```bash
python -m app.check_mongo
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: <http://localhost:8000/docs>  
Health: <http://localhost:8000/api/health>  
Runtime config: <http://localhost:8000/api/config>

### 3. Start the dashboard

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

`frontend/.env` for cloud mode:

```dotenv
VITE_DATA_MODE=cloud
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/ws/readings
```

Open <http://localhost:5173>. Use **Settings → Demo mode** to generate labeled
synthetic readings, or **Manual entry** to add a reading yourself.

### 4. Start the Raspberry Pi client

On the Pi, from `raspberry_pi/`:

```bash
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install requests python-dotenv gpiozero Adafruit-BMP
cp .env.example .env
```

Edit `raspberry_pi/.env`:

```dotenv
AEROSENSE_API_URL=http://192.168.1.100:8000   # backend LAN address
AEROSENSE_API_KEY=                            # same value as DEVICE_API_KEY, if used
AEROSENSE_SITE_NAME=North campus
AEROSENSE_LATITUDE=28.6139
AEROSENSE_LONGITUDE=77.2090
READ_INTERVAL_SECONDS=5
```

Then run:

```bash
python raspberry_pi.py
```

The Pi POSTs to `/api/sensors/readings`; the backend validates the payload,
writes it to MongoDB, evaluates thresholds, updates sensor status and broadcasts
the new reading over WebSocket.

## Mode 1 — Raspberry Pi direct quick start

Run the backend **on the Pi itself**. It reads the sensors in-process and serves
the dashboard on the LAN.

1. On the Pi, install the backend plus the hardware packages:

   ```bash
   cd backend
   python3 -m venv .venv --system-site-packages
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install spidev gpiozero Adafruit-BMP
   cp .env.example .env
   ```

2. Edit `backend/.env`:

   ```dotenv
   DATA_MODE=direct
   STORAGE_BACKEND=file
   STORAGE_PATH=./data/airsense.jsonl
   FILE_MAX_READINGS=100000
   SENSOR_SOURCE=hardware
   HARDWARE_INTERVAL_SECONDS=5
   DEVICE_LOCATION_NAME=North campus
   DEVICE_LATITUDE=28.6139
   DEVICE_LONGITUDE=77.2090
   FRONTEND_ORIGINS=http://localhost:5173,http://192.168.1.50:8000
   ```

   Leave `MONGODB_URI` empty — mode 1 does not use it.

3. Start the API on the Pi:

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

   The startup log should include `mode=direct storage=file sensors=hardware`.

4. Point the dashboard at the Pi. In `frontend/.env`:

   ```dotenv
   VITE_DATA_MODE=direct
   VITE_API_URL=http://192.168.1.50:8000
   VITE_WS_URL=ws://192.168.1.50:8000/ws/readings
   ```

   Restart `npm run dev`. Open `http://localhost:5173` on your laptop (same LAN),
   or serve the built frontend from the Pi.

5. If the dashboard cannot connect, add the browser origin to
   `FRONTEND_ORIGINS` on the Pi and restart the API. For a throwaway demo you can
   use `FRONTEND_ORIGINS=*`.

> Mixed content: a dashboard served over HTTPS cannot open an insecure
> `ws://192.168…` socket. Use HTTP on the LAN, or put the Pi behind a TLS
> reverse proxy.

## Environment files

All sensitive values live in `.env` files that are ignored by git.

| File | Purpose | Commit? |
|---|---|---|
| `backend/.env` | `MONGODB_URI`, database name, device API key, mode | **No** |
| `frontend/.env` | API/WebSocket URLs, mode label | No (contains no secrets) |
| `raspberry_pi/.env` | backend LAN URL, device API key, calibration | No |
| `*.env.example` | documented templates | Yes |

Generate a device key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put it in `backend/.env` as `DEVICE_API_KEY`, and in `raspberry_pi/.env` as
`AEROSENSE_API_KEY`. When `DEVICE_API_KEY` is empty, ingestion is open — fine for
a trusted lab network, not for the public internet.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/sensors/readings` | Validate/store a device payload; `X-API-Key` required when configured |
| `POST` | `/api/sensors/manual` | Store a manual reading (`source: manual`) |
| `GET` | `/api/sensors/latest` | Most recent reading and project score |
| `GET` | `/api/sensors/history` | History; `start`, `end`, `limit`, `source` |
| `GET` | `/api/sensors/locations` | Distinct mapped sites with their latest reading |
| `GET` | `/api/sensors/area` | Nearby 24-hour readings and WHO/CPCB/WMO guidance |
| `GET` | `/api/sensors/statistics` | Min, max, average and counts per field |
| `GET` | `/api/sensors/status` | Last-seen time and online/offline status |
| `GET` | `/api/alerts` | Recent threshold alerts |
| `GET` / `PUT` | `/api/thresholds`, `/api/thresholds/{sensor}` | Read/update `co`, `mq135`, `dust` limits |
| `GET` / `PUT` | `/api/settings/demo` | Read/toggle persisted demo mode |
| `GET` / `PUT` | `/api/settings/demo-location` | Read/set the optional demo station |
| `GET` | `/api/config` | Data mode, storage backend, sensor source |
| `GET` | `/api/health` | Storage connectivity |
| WebSocket | `/ws/readings` | `{"type":"reading","data":...}` updates + latest on connect |

Example device payload (`source` may be omitted or set to `raspberry_pi`):

```json
{
  "timestamp": "2026-11-08T10:00:00Z",
  "temperature": 23.7,
  "pressure": 1011.8,
  "altitude": 112.4,
  "co_ppm": 2.1,
  "mq135_raw": 1.26,
  "dust_voltage": 0.72,
  "dust_ug_m3": 18.5,
  "dust_particle_size": "unknown",
  "location_name": "North campus",
  "latitude": 28.6139,
  "longitude": 77.2090
}
```

All measurements are optional individually, but at least one is required.
Latitude and longitude must be sent together with a site name.
`dust_particle_size` is `unknown`, `pm2_5`, or `pm10`; use PM2.5/PM10 only after
validating the dust sensor for that particle fraction.

## Realtime internals

- Every stored reading is broadcast to connected browsers immediately.
- In MongoDB mode, a change-stream watcher also broadcasts inserts made by other
  processes. A short recent-ID cache prevents duplicate browser updates when
  this API is both the writer and a change-stream consumer.
- Alerts and sensor status are computed exactly once per reading via an atomic
  `alerts_processed` claim. That also makes direct database inserts safe.
- The WebSocket sends the latest reading on connect, then live updates. The
  frontend still uses REST for history, analytics, alerts and settings.

## MongoDB data model

Database: `airsense` (configurable with `MONGODB_DB`).

| Collection | Documents |
|---|---|
| `readings` | One document per sample: timestamp, measurements, source, location, `alerts_processed` |
| `alerts` | Threshold events with severity, message, timestamp, `reading_id` |
| `sensor_status` | `_id` = sensor name, last seen, calibration label |
| `thresholds` | `_id` = `co` / `mq135` / `dust`, warning/critical values |
| `settings` | `_id` = `demo_enabled` / `demo_location`, value |

Indexes are created automatically at startup. Optional retention:

```dotenv
READING_RETENTION_DAYS=30
```

This creates a TTL index on `readings.timestamp`. If you later change the value,
drop the existing `timestamp_ttl` index in Atlas and restart.

The API writes to MongoDB, but the change stream also accepts readings inserted
directly into `airsense.readings` by another trusted process. Such documents
should contain the same fields; alerts are still generated because of the atomic
claim. Direct writes are optional — the recommended path is HTTP through the
backend so validation and API-key checks apply.

## Raspberry Pi wiring and calibration

### Wiring

- MCP3008 `VDD`/`VREF` → 3.3V; `AGND`/`DGND` → GND; `CLK` → GPIO11/SCLK;
  `DOUT` → GPIO9/MISO; `DIN` → GPIO10/MOSI; `CS/SHDN` → GPIO8/CE0.
- MQ-7 analog output → MCP3008 channel 0; MQ-135 → channel 1; Sharp dust →
  channel 2.
- Connect the Sharp LED control to GPIO17 through the correct driver/transistor
  circuit. Follow the datasheet pulse timing.
- **Never connect a 5V analog output directly to the 3.3V MCP3008/Pi.** Use a
  level shifter/voltage divider and a common ground.
- BMP280 is I²C: enable I²C and wire to the correct 3.3V/GND/SDA/SCL pins.

Enable SPI and I²C with `sudo raspi-config`.

### Calibration

The client sends raw MQ-135 volts and only reports CO ppm, estimated MQ-135 ppm
or dust µg/m³ when calibration values are configured. For each MQ sensor,
determine its actual load resistance, burn-in/warm-up and clean-air baseline;
derive and validate an `Rs/R0` curve against known reference concentrations.
Set `{MQ7|MQ135}_R0_KOHM`, `{MQ7|MQ135}_CURVE_SLOPE` and
`{MQ7|MQ135}_CURVE_INTERCEPT` from that calibration. Derive and verify
`DUST_ZERO_VOLTAGE` and `DUST_UG_M3_PER_V` against a reference instrument before
enabling dust estimates. Keep them blank otherwise.

## WHO, CPCB and WMO interpretation

- **WHO:** compare a valid, complete 24-hour mean against the 2021 guideline
  levels: PM2.5 15 µg/m³, PM10 45 µg/m³, CO 4 mg/m³. These are guideline levels,
  not an instant-reading alarm or a personal health diagnosis. CO conversion uses
  each sample's temperature and pressure.
- **CPCB:** when the dust feed is explicitly marked as calibrated PM2.5 or PM10
  and covers the previous 24 hours (at least one observation in every hourly
  period), the area panel shows the CPCB pollutant sub-index and band. It is
  **not** a complete station AQI; this hardware does not measure every pollutant
  required for an official CPCB AQI.
- **WMO:** the dashboard does not invent a WMO pollution severity level. It
  reports when a WMO forecast/alert feed is unavailable. Local readings are not
  an official WMO weather alert.
- Missing coordinates, an uncalibrated particle size, a stale station or
  insufficient hourly coverage produce an “unavailable” status instead of a
  false safe/unsafe warning. A single sample is never compared to a 24-hour
  guideline.

Official references: [WHO Global Air Quality Guidelines (2021)](https://www.who.int/publications/i/item/9789240034228),
[CPCB National AQI FAQ](https://cpcb.nic.in/uploads/Projects/AQI/AQI_Faq.pdf),
[WMO Global Atmosphere Watch](https://wmo.int/activities/global-atmosphere-watch-programme-gaw).

## Security

- Keep `backend/.env` private; it contains the MongoDB URI and device key.
- Use a database user limited to the `airsense` database.
- Set `DEVICE_API_KEY` and `AEROSENSE_API_KEY` before exposing ingestion beyond a
  trusted network.
- Replace `0.0.0.0/0` in Atlas Network Access with specific IPs when possible.
- Use HTTPS/WSS and a restricted `FRONTEND_ORIGINS` list outside the lab.
- Rotate the database password if the URI is ever leaked.
- Enable Atlas backups if you need point-in-time recovery.

## Troubleshooting

### The dashboard says “Reconnecting” / no live data

- Check `VITE_API_URL` and `VITE_WS_URL`. In direct mode they must point at the
  Pi's LAN IP, not `localhost` (unless the dashboard runs on the Pi).
- Allow inbound TCP 8000 on the Pi/backend firewall.
- Confirm the browser origin is in `FRONTEND_ORIGINS`.
- Open `/api/health` directly in the browser.

### `MONGODB_URI is empty` or `ServerSelectionTimeoutError`

- Run the backend from `backend/` so `.env` is loaded.
- Complete [`docs/MONGODB_SETUP.md`](docs/MONGODB_SETUP.md), including the IP
  allowlist and URL-encoded password.
- Run `python -m app.check_mongo` for a clear message.

### Mode 1 starts but there are no readings

- Check the startup log for “Direct hardware mode is enabled but the sensors
  could not be opened.”
- Enable SPI/I²C, verify wiring, and install `spidev gpiozero Adafruit-BMP`.
- Run the API on the Pi (not on your laptop) for hardware mode.

### Alerts are generated twice or not at all

- Do not run two backends that both write the same reading. The atomic claim
  prevents duplicate alerts, but only for reads that reach the same database.
- If you changed thresholds, new readings use the new values; old alerts are not
  rewritten.

## Extending the project

- **Frontend:** navigation is in `frontend/src/components/Sidebar.jsx`; pages and
  composition are in `frontend/src/App.jsx`; API/WebSocket configuration is in
  `frontend/src/services/api.js`.
- **Backend routes:** add endpoints in `backend/app/routes.py`, request validation
  in `schemas.py`, and domain logic in `services.py`.
- **Storage:** add methods to the `Store` interface in `store.py` and implement
  them in `MongoStore` / `MemoryStore`.
- **Hardware:** sensor reads are in `hardware.py` (direct mode) and
  `raspberry_pi/raspberry_pi.py` (cloud mode). Keep their calibration env names
  in sync.
- **Demo simulator:** `simulated_reading()` in `services.py`; cadence comes from
  `DEMO_INTERVAL_SECONDS`.

## Build and deploy

```bash
cd frontend
npm run build
```

Serve `frontend/dist` from a static host or reverse proxy. Run the backend with a
production ASGI server:

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For production: use HTTPS/WSS, a restricted CORS list, `DEVICE_API_KEY`, a
least-privilege MongoDB user, backups, and a process supervisor/systemd unit.
