# AERO-HUB — Smart Air Quality Monitoring

AERO-HUB is a full-stack IoT monitoring starter project. A React dashboard reads sensor data from a FastAPI service, which validates and stores each reading in SQLite by default (or PostgreSQL), produces threshold alerts, and broadcasts new measurements over WebSocket. A Raspberry Pi client can send physical sensor data; development demo mode generates clearly labeled synthetic readings.

> **Measurement note:** the displayed “Project air-quality score” is a simple project indicator, not a regulatory AQI or health assessment. MQ-7/MQ-135 and optical dust sensors require appropriate warm-up, reference measurements, and calibration. Uncalibrated concentration values are not inferred by the Raspberry Pi client.

## Project layout

```text
airsense/
├── frontend/                 # React, Vite, Tailwind, Recharts
│   └── src/
│       ├── components/       # Navigation, metric cards, charts, interactive map
│       ├── hooks/            # WebSocket and live sensor state
│       ├── services/         # REST API client
│       ├── App.jsx           # Pages and dashboard composition
│       └── styles.css        # Responsive dark monitoring UI
├── backend/
│   ├── app/
│   │   ├── database.py       # SQLAlchemy engine and session
│   │   ├── models.py         # Readings, statuses, alerts, thresholds
│   │   ├── schemas.py        # Request validation
│   │   ├── routes.py         # REST API
│   │   ├── services.py       # Alerting, scoring and demo readings
│   │   ├── websocket.py      # Live connection manager
│   │   └── main.py           # FastAPI app and simulator task
│   ├── migrations/           # Alembic environment and schema migrations
│   └── requirements.txt
└── raspberry_pi/
    └── raspberry_pi.py       # MCP3008, BMP280 and HTTP client
```

## Requirements

- Python 3.10+ and Node.js 18+ (Node 20 LTS recommended).
- Windows PowerShell for local development.
- Optional: PostgreSQL 14+ for a persistent/shared deployment.
- Hardware: Raspberry Pi, BMP280, MQ-7, MQ-135, Sharp GP2Y101AU0F, and an MCP3008 ADC for analog sensors.

## Run locally on Windows

Open the `airsense` folder in VS Code. Start a PowerShell terminal in that folder.

### 1. Start the FastAPI backend (SQLite)

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate the environment again. The API docs are available at [http://localhost:8000/docs](http://localhost:8000/docs); health check: [http://localhost:8000/api/health](http://localhost:8000/api/health).

SQLite is the default and creates `backend/airsense.db`. The app calls `create_all` on startup for fresh local installs; use Alembic to apply schema changes. If upgrading an older local install whose tables were created by `create_all` and do not yet have an `alembic_version` table, first back up the database, then from `backend/` mark the old schema as the original release before upgrading:

```powershell
alembic stamp 0001_initial
alembic upgrade head
```

Only run the stamp command when the existing tables match migration `0001_initial`; it preserves existing sensor records and lets Alembic apply subsequent migrations.

### 2. Start the React dashboard

Open a second terminal:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). If the API is on another host, set `VITE_API_URL` in `frontend/.env` and restart Vite. CORS origins are configured by `FRONTEND_ORIGINS` in `backend/.env`.

The site opens on the AeroSense project introduction. Use **Explore the dashboard** to enter monitoring; the AeroSense brand in the dashboard sidebar returns to the introduction.

### 3. Try demo mode or manual entry

In the dashboard choose **Settings → Enable demo mode**. The backend creates one clearly marked `simulation` reading every five seconds, persists it, and publishes it to connected clients. Disable demo mode before expecting hardware readings only. To enter a reading yourself, use **Manual entry**; it is saved with `source: manual`.

Demo mode is off by default. Alternatively set `DEMO_MODE=true` in the backend `.env` before startup. Do not treat generated demo values as sensor measurements.

## PostgreSQL

Create a database and user in PostgreSQL, then set the backend `DATABASE_URL` in `backend/.env`, for example:

```dotenv
DATABASE_URL=postgresql+psycopg://airsense:change-me@localhost:5432/airsense
```

Install the PostgreSQL driver into the backend environment (`pip install psycopg[binary]`), then run `alembic upgrade head` and restart the API. Do not commit credentials. For production, use a managed secret store, HTTPS/WSS, restricted CORS, authentication, backups, and migrations as a deployment step.

## API and live data

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/sensors/readings` | Validate and store Raspberry Pi or simulation payloads, including optional site name and coordinates |
| `POST` | `/api/sensors/manual` | Store manual readings, overriding source to `manual` |
| `GET` | `/api/sensors/latest` | Most recent reading and project score |
| `GET` | `/api/sensors/history` | History, optional `start`, `end`, `limit`, `source` query params |
| `GET` | `/api/sensors/locations` | Distinct mapped sensor sites and their latest readings |
| `GET` | `/api/sensors/area?latitude=…&longitude=…&radius_km=5` | Nearby readings and conservative 24-hour WHO/CPCB guidance |
| `GET` | `/api/sensors/statistics` | Min, max, average, and counts by field |
| `GET` | `/api/sensors/status` | Last-seen time and current sensor status (offline after 30 seconds) |
| `GET` | `/api/alerts` | Recent threshold alerts |
| `GET` / `PUT` | `/api/thresholds` and `/api/thresholds/{sensor_name}` | Read/update `co`, `mq135`, and `dust` limits |
| `GET` / `PUT` | `/api/settings/demo` | Read or toggle persisted demo-mode setting |
| `GET` / `PUT` | `/api/settings/demo-location` | Read or set the persisted optional demo station name and coordinates |
| `GET` | `/api/health` | Database connectivity check |
| WebSocket | `/ws/readings` | Push `{"type":"reading","data":...}` updates |

Example device payload (send JSON with `source` omitted or set to `raspberry_pi`):

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

All measurements are optional individually, but at least one must be included. Latitude and longitude must be sent together with a site name. `dust_particle_size` is `unknown`, `pm2_5`, or `pm10`; select PM2.5/PM10 only after validating and calibrating the dust sensor for that particle fraction. The interactive Overview map plots geotagged records; select a marker or map point to inspect readings within a 1–25 km radius. Data is queried from the database, not geocoded or fabricated. CSV exports include location and particle-size metadata.

## WHO, CPCB, and WMO warning interpretation

- **WHO:** compare a valid, complete 24-hour mean against the 2021 guideline levels: PM2.5 15 µg/m³, PM10 45 µg/m³, and CO 4 mg/m³. These are guideline levels, not an instant-reading alarm or a personal health diagnosis. The CO conversion from ppm uses each sample's temperature and pressure.
- **CPCB:** when the dust feed is explicitly marked as calibrated PM2.5 or PM10 and covers the previous 24 hours (at least one observation in each hourly period), the area panel displays the CPCB pollutant sub-index and its Good/Satisfactory/Moderate/Poor/Very Poor/Severe band. It is **not** a complete station AQI: this hardware does not measure all pollutants required to publish an official CPCB AQI.
- **WMO:** the dashboard does not invent a WMO pollution severity level. It reports when a WMO forecast/alert feed is unavailable; WMO atmospheric monitoring and forecast products need a real external data feed to show an official weather or dust-storm warning.
- Missing coordinates, an uncalibrated particle-size estimate, a stale station, or insufficient hourly coverage produce an unavailable status rather than a false safe/unsafe warning. A single sensor sample is never compared to a 24-hour guideline.

Official references: [WHO Global Air Quality Guidelines (2021)](https://www.who.int/publications/i/item/9789240034228), [CPCB National AQI FAQ](https://cpcb.nic.in/uploads/Projects/AQI/AQI_Faq.pdf), and [WMO Global Atmosphere Watch](https://wmo.int/activities/global-atmosphere-watch-programme-gaw).

## Raspberry Pi integration

### Wiring and prerequisites

- MCP3008 `VDD`/`VREF` → 3.3V; `AGND`/`DGND` → GND; `CLK` → GPIO11/SCLK; `DOUT` → GPIO9/MISO; `DIN` → GPIO10/MOSI; `CS/SHDN` → GPIO8/CE0.
- Connect the MQ-7 analog output and MQ-135 analog output to MCP3008 channels 0 and 1; Sharp sensor analog output to channel 2.
- Connect the Sharp sensor LED control to GPIO17 through the correct driver/transistor circuit. Observe the Sharp datasheet pulse timing and protect Raspberry Pi inputs from 5V signals.
- **Do not connect a 5V analog output directly to the 3.3V MCP3008/Raspberry Pi.** Use a suitable level/voltage divider and common ground. Follow each sensor module's datasheet and warm-up requirements.
- BMP280 is I²C; enable I²C and wire to the correct 3.3V/GND/SDA/SCL pins. Verify module voltage tolerance.

Enable SPI and I²C using `sudo raspi-config`. Then on Raspberry Pi OS:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip python3-spidev
cd raspberry_pi
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install requests python-dotenv gpiozero Adafruit-BMP
```

Set environment variables (for example in a local `.env`, never commit it):

```dotenv
AEROSENSE_API_URL=http://<WINDOWS-PC-LAN-IP>:8000
READ_INTERVAL_SECONDS=5
ADC_VREF=3.3
MQ7_ADC_CHANNEL=0
MQ135_ADC_CHANNEL=1
DUST_ADC_CHANNEL=2
DUST_LED_GPIO=17
MQ_LOAD_RESISTOR_KOHM=10
AEROSENSE_SITE_NAME=North campus
AEROSENSE_LATITUDE=28.6139
AEROSENSE_LONGITUDE=77.2090
DUST_PARTICLE_SIZE=unknown
```

Run `python raspberry_pi.py`. Keep both devices on a reachable network and allow inbound TCP port 8000 on the development PC firewall only for the trusted local network. The script retries failed POSTs with backoff and logs sensor/network errors.

For simulator mapping, open **Settings → Demo station location**, enter a site label plus latitude/longitude, and save. New simulated samples then appear on the map. Leaving coordinates blank keeps demo samples unmapped.

The client sends raw MQ-135 volts, and reports CO ppm, estimated MQ-135 ppm, or dust µg/m³ only when the calibration configuration is provided. For each MQ sensor determine its actual load resistance, burn-in/warm-up and baseline in clean air; derive and validate an `Rs/R0` curve using known reference gas concentrations. Set `{MQ7|MQ135}_R0_KOHM`, `{MQ7|MQ135}_CURVE_SLOPE`, and `{MQ7|MQ135}_CURVE_INTERCEPT` from that calibration. The generic power curve helper is not a substitute for the sensor-specific datasheet/procedure. Derive and verify `DUST_ZERO_VOLTAGE` and `DUST_UG_M3_PER_V` against a reference before enabling dust estimates. Keep them unset otherwise.

## Extending the project

- **Frontend:** navigation lives in `frontend/src/components/Sidebar.jsx`; page UI and composition are in `frontend/src/App.jsx`; reusable chart and metric components are in `frontend/src/components/`. The API helper is in `frontend/src/services/api.js`. Add new page IDs to the sidebar and render them from `App.jsx`.
- **Backend APIs:** add routes in `backend/app/routes.py`, request/response types in `schemas.py`, and business logic in `services.py`. The `save_reading` service is shared by device, manual, and simulator paths.
- **Database schema:** edit SQLAlchemy classes in `backend/app/models.py`, generate a migration from `backend/` with `alembic revision --autogenerate -m "describe change"`, inspect it, and apply with `alembic upgrade head`. Avoid editing an already-applied migration.
- **Simulator:** generation and configured cadence are in `backend/app/services.py` and `backend/app/main.py`; demo records use `simulation` source.
- **Styling:** `frontend/src/styles.css` defines the dark responsive visual system and uses Tailwind directives; responsive breakpoints can be adjusted there.

## Build and deployment

Verify the frontend bundle with `cd frontend; npm run build`. For backend deployment run `uvicorn app.main:app --host 0.0.0.0 --port 8000` from `backend` behind a production ASGI server/reverse proxy and TLS. Build and serve `frontend/dist` using a static host or reverse proxy. Configure `VITE_API_URL`, backend database credentials, allowed origins, and migrations per environment.

Before exposing beyond a trusted lab network, add authentication/device credentials, TLS/WSS, rate limits, secure secret storage, and a deployment-specific CORS allow-list. The starter API intentionally does not claim production device authentication.
