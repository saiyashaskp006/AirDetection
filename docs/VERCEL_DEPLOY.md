# Host the dashboard on Vercel, with the backend on the Pi

This is the setup that removes the laptop from the live path:

```text
Arduino Uno ──UART──► Raspberry Pi
                        │
                        ├─ FastAPI backend ──► MongoDB Atlas (history)
                        │  reads sensors, serves REST + WebSocket
                        │
                        └─ Tailscale Funnel / Cloudflare Tunnel
                                   │ HTTPS + WSS
                                   ▼
                              Vercel frontend
```

The laptop is only needed to flash the Arduino and deploy the frontend. Once the
Pi is running, the Vercel site can show live data and history without the laptop.

## 1. Run the backend on the Pi

Clone or copy the repository to the Pi. For example:

```bash
git clone <your-repo-url> ~/AirDetection
# or copy the folder over SSH / a USB drive
```

On the Pi, install both sets of dependencies. `--system-site-packages` lets the
CircuitPython/GPIO packages see the Pi's system libraries.

```bash
cd ~/AirDetection/backend
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -r requirements.txt
pip install -r ../raspberry_pi/requirements.txt
```

Make sure the Pi user can access the hardware:

```bash
sudo usermod -aG dialout,i2c,spi,gpio "$USER"
```

Log out and back in (or reboot) after changing groups.

Enable I2C and the serial port if you have not already:

```bash
sudo raspi-config
# Interface Options -> I2C -> Yes
# Interface Options -> Serial Port:
#   login shell over serial? -> No
#   serial port hardware enabled? -> Yes
sudo reboot
```

After the reboot:

```bash
ls -l /dev/serial0        # GPIO UART
# or
ls -l /dev/ttyACM0        # Arduino over USB
```

The Pi has no hardware clock. Confirm that time synchronization is active so
reading timestamps are correct:

```bash
timedatectl
```

`System clock synchronized: yes` is what you want.

### `backend/.env` for the Pi

A ready-to-edit template is in
[`deploy/pi-backend.env.example`](../deploy/pi-backend.env.example):

```bash
cp ~/AirDetection/deploy/pi-backend.env.example ~/AirDetection/backend/.env
nano ~/AirDetection/backend/.env
```

Use the **same Atlas database** that the laptop backend used. That is what makes
the old history visible from the Vercel site. The important values are:

```dotenv
DATA_MODE=direct
STORAGE_BACKEND=mongodb

MONGODB_URI=mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/
MONGODB_DB=airsense
MONGODB_CHANGE_STREAM=true
# 0 keeps all existing history. For continuous 1 Hz operation, set 7: a week
# is roughly 200 MB and fits the 512 MB Atlas free tier.
READING_RETENTION_DAYS=0

# This process reads the sensors itself; do not also run raspberry_pi.py.
SENSOR_SOURCE=hardware
HARDWARE_INTERVAL_SECONDS=1

# Optional ingestion protection. Keep it set even if the external POST route is
# not used, in case you later switch back to a separate Pi client.
DEVICE_API_KEY=your-long-random-key

# Where the station is. These replace AEROSENSE_SITE_NAME/LATITUDE/LONGITUDE.
DEVICE_LOCATION_NAME=North campus
DEVICE_LATITUDE=28.6139
DEVICE_LONGITUDE=77.2090

# The browser origin is the Vercel site, not the tunnel URL.
FRONTEND_ORIGINS=https://your-project.vercel.app

# Hardware settings, same values as the old raspberry_pi/.env. The backend
# loads only backend/.env; it does not read raspberry_pi/.env.
ADC_BACKEND=arduino
ARDUINO_PORT=/dev/serial0
ARDUINO_BAUD=115200
ARDUINO_BOOT_SECONDS=0
ARDUINO_VREF=5.0
ARDUINO_ADC_MAX=1023
ARDUINO_DUST_LED=true
MQ_DIVIDER_RATIO=1
DUST_DIVIDER_RATIO=1
BMP280_I2C_ADDRESS=0x77
GPS_ENABLED=false
LCD_ENABLED=false

# Optional calibration, same names as raspberry_pi/.env. Leave blank until you
# have real reference values; raw voltages still upload.
MQ7_R0_KOHM=
MQ7_CURVE_SLOPE=
MQ7_CURVE_INTERCEPT=
MQ135_R0_KOHM=
MQ135_CURVE_SLOPE=
MQ135_CURVE_INTERCEPT=
DUST_ZERO_VOLTAGE=
DUST_UG_M3_PER_V=
```

If you use the Uno over USB instead of the GPIO UART, set:

```dotenv
ARDUINO_PORT=/dev/ttyACM0
ARDUINO_BOOT_SECONDS=2.0
```

Start the backend manually once to prove it works:

```bash
cd ~/AirDetection/backend
source .venv/bin/activate
python -m app.check_mongo
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

> Do not run the laptop backend or `raspberry_pi.py` at the same time as this
> Pi backend. In direct mode the backend reads the sensors itself; a second
> writer would create duplicate readings. Keep Uvicorn at **one worker**; more
> workers would each try to open the Arduino and run their own change stream.

On the Pi:

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/sensors/latest
```

The startup log should say:

```text
mode=direct storage=mongodb sensors=hardware change_stream=True
```

## 2. Expose the Pi backend over HTTPS

Vercel serves the frontend over HTTPS. A browser on an HTTPS page cannot call
`http://10.58.197.199:8000` or `ws://...`: that is mixed content and is blocked.
You need a public HTTPS/WSS endpoint.

Do **not** port-forward port 8000 directly. Use a tunnel.

### Option A — Tailscale Funnel (recommended: no domain needed)

On the Pi:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale funnel --bg 8000
sudo tailscale funnel status
```

If Tailscale asks you to enable HTTPS or Funnel for the tailnet, open the link it
prints and enable them in the Tailscale admin console.

The public URL looks like:

```text
https://raspberrypi.tailXXXX.ts.net
```

Test it from the Pi or another network:

```bash
curl https://raspberrypi.tailXXXX.ts.net/api/health
```

Tailscale Funnel supports WebSockets, so `wss://.../ws/readings` works. The funnel
runs as part of `tailscaled` and survives reboots.

### Option B — Cloudflare Tunnel (stable custom domain)

Install `cloudflared` on the Pi. For a quick throwaway test:

```bash
cloudflared tunnel --url http://localhost:8000
```

That prints a temporary `https://....trycloudflare.com` URL. It changes when the
tunnel restarts, so it is not suitable for a permanent Vercel deployment.

For a permanent URL, create a named tunnel in the Cloudflare Zero Trust
dashboard, route a hostname such as `api.example.com` to
`http://localhost:8000`, and install the connector as a service. Cloudflare
Tunnel supports WebSockets. Tailscale Funnel is simpler if you do not already
have a domain.

## 3. Keep the backend running on the Pi

Copy the sample service file and edit the paths/user if needed:

```bash
sudo cp ~/AirDetection/deploy/aerohub-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aerohub-backend
sudo systemctl status aerohub-backend
```

Logs:

```bash
journalctl -u aerohub-backend -f
```

The sample uses `--host 127.0.0.1` because the tunnel runs on the same Pi. Change
it to `0.0.0.0` only if you also want LAN clients to connect directly.

After a reboot, check:

```bash
curl http://127.0.0.1:8000/api/health
```

## 4. Deploy the frontend on Vercel

1. Push the repository to GitHub/GitLab.
2. In Vercel, **Add New → Project** and import the repository.
3. Set **Root Directory** to `frontend`.
4. Framework preset: **Vite**.
5. Build command: `npm run build`.
6. Output directory: `dist`.
7. Add these environment variables for **Production** (and Preview if you use it):

```dotenv
VITE_DATA_MODE=direct
VITE_API_URL=https://raspberrypi.tailXXXX.ts.net
VITE_WS_URL=wss://raspberrypi.tailXXXX.ts.net/ws/readings
```

Use the exact URL from your tunnel. No trailing slash.

8. Deploy. Vite environment variables are baked in at build time, so **redeploy
   after changing any `VITE_*` value**.

9. Copy the final Vercel domain (for example `https://aerohub.vercel.app`) into
   `FRONTEND_ORIGINS` on the Pi:

```dotenv
FRONTEND_ORIGINS=https://aerohub.vercel.app,http://localhost:5173
```

Restart the backend:

```bash
sudo systemctl restart aerohub-backend
```

CORS is checked by the browser for the REST requests. The WebSocket route does
not use CORS, but the REST calls must match `FRONTEND_ORIGINS` exactly.

## 5. Verify live data and history

From the Vercel URL:

1. The topbar should say **Live connected**.
2. The timestamp should advance every second.
3. Open **Analytics** and request 1 hour, 24 hours, or 7 days. The data comes from
   Atlas through the Pi backend, so readings recorded while the laptop was
   running still appear.

Useful checks:

```bash
# On the Pi
curl http://127.0.0.1:8000/api/sensors/latest
curl 'http://127.0.0.1:8000/api/sensors/history?limit=5'

# Through the tunnel
curl https://raspberrypi.tailXXXX.ts.net/api/health
curl https://raspberrypi.tailXXXX.ts.net/api/sensors/latest
```

If the tunnel URL is unreachable, the Vercel frontend cannot show history —
Vercel only serves static files. The backend must be running somewhere.

At 1 Hz, the raw history endpoint returns at most 50,000 rows, which is about
14 hours. The 1-hour chart is complete; the 24-hour and 7-day line charts show
the newest 50,000 rows, while the statistics cards cover the full selected
period. If you need full-range 24-hour/7-day line charts at 1 Hz, add
server-side downsampling (one averaged point per bucket) instead of raising the
limit.

## Why history disappeared when the laptop was off

The browser cannot query MongoDB directly: that would expose the database
credentials, and change streams need a persistent server process. The frontend
only talks to the FastAPI backend. If the only backend was on the laptop, turning
the laptop off removed every API endpoint, so the website had no source for old
or new readings.

Running the backend on the Pi fixes that for as long as the Pi is powered and
online. The history itself is safe in Atlas; the Pi backend is the process that
reads it back.

If you need history to remain available **even when the Pi is off**, the backend
must run on an always-on cloud host instead of the Pi. In that layout:

```text
Pi (raspberry_pi.py) ──HTTPS──► Render/Fly/Railway backend ──► Atlas
                                           ▲
                                           └── Vercel frontend (REST + WSS)
```

The Pi only posts readings; the cloud backend serves history and live updates.
Render's free web service is enough for a low-traffic demo, but free instances can
sleep after inactivity; 1 Hz traffic normally keeps one awake. In that layout,
point `AEROSENSE_API_URL` at the cloud backend and set its `FRONTEND_ORIGINS` to
the Vercel domain.

## Troubleshooting

### CORS error in the browser console

`FRONTEND_ORIGINS` must contain the exact origin shown in the address bar,
including `https://` and without a trailing slash:

```dotenv
FRONTEND_ORIGINS=https://aerohub.vercel.app
```

For temporary Vercel preview URLs, add each preview origin, or use
`FRONTEND_ORIGINS=*` only for a short test. Restart the backend after editing.

### Vercel loads but every request goes to `localhost`

The `VITE_*` values were missing at build time, or you did not redeploy after
adding them. Set them in Vercel → Settings → Environment Variables, then trigger
a new deployment.

### Mixed-content or WebSocket errors

The page is HTTPS, so the backend must be `https://` and the socket `wss://`.
A plain `http://` or `ws://` tunnel URL will be blocked. Both Tailscale Funnel
and Cloudflare Tunnel provide HTTPS/WSS.

### Tunnel returns 502 / 404

- Is `systemctl status aerohub-backend` running?
- Is it bound to the port the tunnel targets (`8000`)?
- Does `curl http://127.0.0.1:8000/api/health` work on the Pi?
- For Tailscale Funnel, check `sudo tailscale funnel status`.

### WebSocket disconnects but REST works

Some proxies do not forward WebSockets. The dashboard falls back to polling
`/api/sensors/latest` every 2 seconds, so data still updates. For true 1 Hz live
updates, use a tunnel that supports WebSockets (Tailscale Funnel and Cloudflare
Tunnel both do).

### No old readings

- Keep `STORAGE_BACKEND=mongodb`; file storage on the Pi will not contain the
  readings written by the laptop backend.
- Keep the same `MONGODB_DB=airsense` and `MONGODB_URI` as before.
- Check `curl 'http://127.0.0.1:8000/api/sensors/history?limit=5'` on the Pi.

### Atlas connection fails from the Pi

Atlas Network Access must allow the Pi's public IP. For a demo, `0.0.0.0/0` is
the simplest; for a permanent deployment, restrict it. Run
`python -m app.check_mongo` on the Pi for a clear error.
