# MongoDB Atlas setup (free tier)

This guide sets up the cloud database used by **mode 2**. It takes about ten
minutes and does not require a credit card.

## Is the feature free?

Yes — with one important distinction:

| Capability | Free-tier status |
|---|---|
| MongoDB Atlas Free cluster (formerly `M0`) | Available: 512 MB storage, 100 ops/sec, 500 connections |
| MongoDB **change streams** (realtime inserts) | Available on the free cluster (it is a 3-node replica set) |
| Atlas Device Sync / App Services (the old “realtime database” product) | **Retired on 30 September 2025** — do not build on it |
| Atlas database triggers | Available, but not needed here |

AERO-HUB therefore uses **change streams + WebSocket**, not Device Sync:

```text
Raspberry Pi --HTTP POST--> FastAPI --insert--> MongoDB Atlas
                                                  |
                                     change stream (free tier)
                                                  |
                                    FastAPI --WebSocket--> Browser
```

The browser also uses the REST API for history, statistics, alerts and settings.
Database credentials stay on the backend and are never sent to the browser.

Free-tier limits to keep in mind:

- 512 MB total storage. A reading is roughly 250–400 bytes, so a 5-second
  interval is around 5–7 MB/day. Set `READING_RETENTION_DAYS=30` if you want a
  predictable ceiling.
- 100 read/write operations per second.
- 10 GB in and 10 GB out per rolling seven days.
- Idle clusters pause after 30 days without connections; open the Atlas UI to
  resume.

## 1. Create the cluster

1. Sign in at <https://www.mongodb.com/cloud/atlas> (or create an account).
2. Create a **Project** (for example `AERO-HUB`).
3. Click **Build a Database** / **Create**.
4. Choose the **Free** / **M0** tier. The free tier is enough for this project.
5. Pick a provider and a region close to you. Any offered free region works.
6. Name the cluster (for example `aerohub`) and create it.
7. Wait until the cluster status is **Active** (a minute or two).

## 2. Create a database user

1. In the cluster, open **Database Access** (left sidebar).
2. **Add New Database User**.
3. Choose **Password** authentication.
4. Username: `aerohub`. Password: generate a long random one and save it in a
   password manager.
5. Privileges: **Read and write to any database** is the simplest choice for a
   single-project demo. For tighter security, grant read/write only on the
   `airsense` database.
6. Create the user.

Do not use your Atlas account password for this. The database user is separate.

## 3. Allow your backend's IP address

1. Open **Network Access**.
2. **Add IP Address**.
3. For a quick local test you can add `0.0.0.0/0` (allow from anywhere). This is
   convenient but less secure; replace it with your real public IP later.
4. If the backend runs on a home computer or Raspberry Pi, add that network's
   public IP. The Pi itself does not connect to MongoDB in this project — only
   the backend does.

If you use a dynamic home IP and see connection timeouts later, re-check this
list first.

## 4. Get the connection string

1. Open the cluster and click **Connect**.
2. Choose **Drivers**.
3. Driver: **Python**, version 3.12 or newer.
4. Copy the connection string. It looks like:

   ```text
   mongodb+srv://aerohub:<db_password>@cluster0.ab12c.mongodb.net/?retryWrites=true&w=majority&appName=aero-hub
   ```

5. Replace `<db_password>` with the password from step 2. If the password has
   special characters, URL-encode them:

   | Character | Encoded |
   |---|---|
   | `@` | `%40` |
   | `:` | `%3A` |
   | `/` | `%2F` |
   | `#` | `%23` |
   | `?` | `%3F` |
   | `&` | `%26` |

## 5. Put it in `backend/.env`

Open `backend/.env` and set:

```dotenv
DATA_MODE=cloud
STORAGE_BACKEND=mongodb
MONGODB_URI=mongodb+srv://aerohub:YOUR_PASSWORD@cluster0.ab12c.mongodb.net/?retryWrites=true&w=majority&appName=aero-hub
MONGODB_DB=airsense
MONGODB_CHANGE_STREAM=true
READING_RETENTION_DAYS=0
```

`backend/.env` is ignored by git. Never paste this URI into the frontend, a
screenshot, a commit, or the Raspberry Pi `.env`.

## 6. Verify the connection

From the `backend` directory:

```bash
source .venv/bin/activate
python -m app.check_mongo
```

Expected output:

```text
Connecting to mongodb+srv://aerohub:***@cluster0.ab12c.mongodb.net/...
MongoDB is ready.
  database      : airsense
  readings      : 0 documents
  change stream : True
  indexes       : location, source, timestamp_desc
```

The command creates the `readings`, `alerts`, `sensor_status`, `thresholds` and
`settings` collections the first time the API writes to them, and seeds the
default alert thresholds.

## 7. Start the API and confirm realtime data

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then, in another terminal:

```bash
curl http://localhost:8000/api/health
```

You should see `"storage": {"backend": "mongodb", ...}`. Open the dashboard with
`VITE_DATA_MODE=cloud` and `VITE_API_URL=http://localhost:8000`.

## Troubleshooting

### `ServerSelectionTimeoutError` / `SSL handshake failed`

- The cluster is still provisioning or paused.
- The backend's public IP is not in **Network Access**.
- A corporate/school network blocks outbound TLS to port 27017. Try another
  network or a mobile hotspot to confirm.
- The password or username is wrong, or special characters were not encoded.

### `bad auth : Authentication failed`

Reset the database user's password in **Database Access** and update
`MONGODB_URI`. Remember to URL-encode the new password.

### `MONGODB_URI is empty`

You are running from the wrong directory, or the `.env` file is not next to the
backend. Run `uvicorn app.main:app` from `backend/`, because `python-dotenv`
loads `./.env`.

### Change streams do not deliver updates

- Keep `MONGODB_CHANGE_STREAM=true`. Free clusters support change streams.
- If you use a self-hosted *standalone* `mongod` instead of Atlas, change
  streams are unavailable (they require a replica set). The API still broadcasts
  readings it inserts itself; only writes made by other processes are missed.
- Check the backend log for `MongoDB change stream interrupted`. It retries
  automatically.

### Reading the data manually

In Atlas, open **Browse Collections** → `airsense` → `readings`. You can also
use `mongosh` with the same connection string.

## Security checklist

- Keep the connection string in `backend/.env` only.
- Use a database user limited to the `airsense` database in production.
- Replace `0.0.0.0/0` in Network Access with specific IPs when possible.
- Rotate the database password if it is ever exposed.
- Set `DEVICE_API_KEY` in `backend/.env` and `AEROSENSE_API_KEY` in
  `raspberry_pi/.env` so random devices cannot post readings.
- Serve the dashboard over HTTPS/WSS before exposing it outside your LAN.
- Enable free-cluster backups if you care about retaining history.
