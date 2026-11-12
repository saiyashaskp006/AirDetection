"""Optional Raspberry Pi peripherals: phone GPS and a 16x2 I2C LCD.

The GPS helper reads NMEA sentences straight from an Android/iPhone app, so
gpsd is not required. The LCD helper renders the latest reading on a
PCF8574-backed 16x2 display.

Only the standard library is imported at module level. The LCD library
(``RPLCD``) is imported lazily, so this module stays importable on a laptop
without hardware.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from typing import Any

logger = logging.getLogger("airsense.peripherals")


# --------------------------------------------------------------------------- env


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw, 0)
    except ValueError:
        return default


# ----------------------------------------------------------------------- NMEA


def nmea_checksum(sentence: str) -> int:
    """XOR of every character between ``$`` and ``*``."""
    body = sentence.lstrip("$").split("*", 1)[0]
    value = 0
    for char in body:
        value ^= ord(char)
    return value


def _checksum_ok(sentence: str) -> bool:
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    _, _, checksum = sentence[1:].partition("*")
    try:
        expected = int(checksum[:2], 16)
    except ValueError:
        return False
    return nmea_checksum(sentence) == expected


def _degrees_minutes(value: str, hemisphere: str) -> float | None:
    """Convert NMEA ``ddmm.mmmm`` / ``dddmm.mmmm`` to decimal degrees."""
    if not value:
        return None
    try:
        raw = float(value)
    except ValueError:
        return None
    degrees = int(raw // 100)
    minutes = raw - degrees * 100
    if minutes >= 60:
        return None
    decimal = degrees + minutes / 60
    if hemisphere in ("S", "W"):
        decimal = -decimal
    return round(decimal, 7)


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_nmea(sentence: str) -> dict[str, Any] | None:
    """Parse one GGA/RMC/GSA sentence into a partial fix.

    Returns ``None`` for checksum failures, malformed text, or sentence types
    this project does not use.
    """
    sentence = sentence.strip()
    if not _checksum_ok(sentence):
        return None

    body = sentence[1:].split("*", 1)[0]
    parts = body.split(",")
    if len(parts) < 2 or len(parts[0]) < 5:
        return None
    kind = parts[0][2:]  # strip the talker id: GP, GN, GL, GA, BD, ...

    if kind == "GGA" and len(parts) >= 10:
        quality = _to_float(parts[6])
        latitude = _degrees_minutes(parts[2], parts[3])
        longitude = _degrees_minutes(parts[4], parts[5])
        if quality is None or quality <= 0 or latitude is None or longitude is None:
            return {"type": "GGA", "fix_quality": 0}
        return {
            "type": "GGA",
            "fix_quality": int(quality),
            "latitude": latitude,
            "longitude": longitude,
            "satellites": _to_float(parts[7]),
            "hdop": _to_float(parts[8]),
            "altitude": _to_float(parts[9]),
        }

    if kind == "RMC" and len(parts) >= 10:
        if parts[2] != "A":
            return {"type": "RMC", "fix_quality": 0}
        latitude = _degrees_minutes(parts[3], parts[4])
        longitude = _degrees_minutes(parts[5], parts[6])
        if latitude is None or longitude is None:
            return None
        return {
            "type": "RMC",
            "fix_quality": 1,
            "latitude": latitude,
            "longitude": longitude,
            "speed_knots": _to_float(parts[7]),
            "course": _to_float(parts[8]),
        }

    if kind == "GSA" and len(parts) >= 3:
        mode = parts[1] or "?"
        fix_type = _to_float(parts[2])
        return {"type": "GSA", "fix_quality": int(fix_type or 0), "mode": mode}

    return None


# ------------------------------------------------------------------------ GPS


class PhoneGPS:
    """Read NMEA from a phone app over TCP or UDP.

    ``mode="tcp"``: the phone runs a listener and this class connects to it
    (works with gpsdRelay "TCP server" and Share GPS "NMEA / TCP / Listen").

    ``mode="udp"``: this class binds a local port and the phone sends datagrams
    to it (works with GPSd Forwarder, the app in the KM4ACK video).
    """

    def __init__(
        self,
        mode: str = "tcp",
        host: str = "",
        port: int = 10110,
        max_age_seconds: float = 30.0,
    ) -> None:
        self.mode = mode
        self.host = host
        self.port = port
        self.max_age_seconds = max_age_seconds

        self._lock = threading.Lock()
        self._buffer = b""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fix: dict[str, Any] = {
            "latitude": None,
            "longitude": None,
            "altitude": None,
            "satellites": None,
            "hdop": None,
            "fix_quality": 0,
            "speed_knots": None,
            "course": None,
            "updated": None,
        }
        self._connected = False

    # -- lifecycle
    def start(self) -> None:
        if self.mode not in {"tcp", "udp"}:
            raise ValueError(f"Unsupported GPS mode: {self.mode!r}")
        if self.mode == "tcp" and not self.host:
            raise ValueError("GPS_HOST is required for GPS_MODE=tcp")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="phone-gps", daemon=True)
        self._thread.start()
        logger.info(
            "GPS reader started (mode=%s target=%s:%s)",
            self.mode,
            self.host or "*",
            self.port,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    # -- data
    def snapshot(self) -> dict[str, Any] | None:
        """Return the latest fix, or ``None`` when there is no recent fix."""
        with self._lock:
            fix = dict(self._fix)
        if fix["latitude"] is None or fix["longitude"] is None:
            return None
        updated = fix.pop("updated")
        if updated is None:
            return None
        age = time.monotonic() - updated
        if age > self.max_age_seconds:
            return None
        fix["age_seconds"] = round(age, 1)
        return fix

    def status(self) -> str:
        """Short human-readable state for the LCD."""
        with self._lock:
            connected = self._connected
            fix = dict(self._fix)
        if fix["latitude"] is None:
            return "GPS connected" if connected else "GPS waiting"
        age = time.monotonic() - fix["updated"] if fix["updated"] else None
        if age is not None and age > self.max_age_seconds:
            return f"GPS stale {int(age)}s"
        sats = fix.get("satellites")
        return f"GPS {int(sats)}sat" if sats else "GPS fix"

    # -- worker
    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                if self.mode == "udp":
                    self._udp_loop()
                else:
                    self._tcp_loop()
                failures = 0
            except OSError as exc:
                failures += 1
                if failures == 1 or failures % 12 == 0:
                    logger.warning("GPS connection failed (%s attempt(s)): %s", failures, exc)
            finally:
                with self._lock:
                    self._connected = False
            self._stop.wait(5)

    def _tcp_loop(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=10) as sock:
            sock.settimeout(5)
            logger.info("GPS connected to %s:%s", self.host, self.port)
            with self._lock:
                self._connected = True
                self._buffer = b""
            while not self._stop.is_set():
                try:
                    chunk = sock.recv(4096)
                except TimeoutError:
                    continue
                if not chunk:
                    logger.warning("GPS stream closed by the phone")
                    return
                self._feed(chunk)

    def _udp_loop(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.port))
            sock.settimeout(1.0)
            logger.info("GPS listening for UDP NMEA on port %s", self.port)
            with self._lock:
                self._connected = True
            while not self._stop.is_set():
                try:
                    chunk, _ = sock.recvfrom(4096)
                except TimeoutError:
                    continue
                for line in chunk.replace(b"\r", b"\n").split(b"\n"):
                    self._ingest(line.decode("ascii", "ignore"))
                with self._lock:
                    self._connected = True

    def _feed(self, chunk: bytes) -> None:
        with self._lock:
            self._buffer += chunk
            lines = self._buffer.split(b"\n")
            self._buffer = lines.pop()
        for line in lines:
            self._ingest(line.decode("ascii", "ignore"))

    def _ingest(self, line: str) -> None:
        parsed = parse_nmea(line)
        if parsed is None:
            return

        now = time.monotonic()
        with self._lock:
            if parsed.get("fix_quality", 0) <= 0:
                if parsed.get("type") in {"GGA", "RMC"}:
                    self._fix["fix_quality"] = 0
                return
            if "latitude" in parsed:
                self._fix["latitude"] = parsed["latitude"]
                self._fix["longitude"] = parsed["longitude"]
                self._fix["updated"] = now
            for key in ("altitude", "satellites", "hdop", "speed_knots", "course"):
                if parsed.get(key) is not None:
                    self._fix[key] = parsed[key]
            if parsed.get("fix_quality"):
                self._fix["fix_quality"] = parsed["fix_quality"]


def create_gps() -> PhoneGPS | None:
    """Build a :class:`PhoneGPS` from the environment, or ``None`` if disabled."""
    if not _env_bool("GPS_ENABLED", False):
        return None
    mode = os.getenv("GPS_MODE", "tcp").strip().lower() or "tcp"
    try:
        gps = PhoneGPS(
            mode=mode,
            host=os.getenv("GPS_HOST", "").strip(),
            port=_env_int("GPS_PORT", 10110),
            max_age_seconds=_env_float("GPS_MAX_AGE_SECONDS", 30.0),
        )
        gps.start()
        return gps
    except (OSError, ValueError) as exc:
        logger.warning("GPS disabled: %s", exc)
        return None


def apply_gps(payload: dict[str, Any], fix: dict[str, Any] | None) -> dict[str, Any]:
    """Merge a GPS fix into a reading payload.

    ``location_name`` is required by the API whenever coordinates are present,
    so keep the configured site name, or fall back to ``GPS_LOCATION_NAME``.
    """
    if not fix or fix.get("latitude") is None or fix.get("longitude") is None:
        return payload
    payload["latitude"] = fix["latitude"]
    payload["longitude"] = fix["longitude"]
    if not payload.get("location_name"):
        payload["location_name"] = os.getenv("GPS_LOCATION_NAME", "Mobile GPS").strip() or "Mobile GPS"
    if payload.get("altitude") is None and fix.get("altitude") is not None:
        payload["altitude"] = fix["altitude"]
    return payload


# ------------------------------------------------------------------------ LCD


def _fmt(value: Any, template: str = "{:.1f}", suffix: str = "") -> str:
    if value is None:
        return "n/a"
    try:
        return template.format(value) + suffix
    except (TypeError, ValueError):
        return "n/a"


class LcdDisplay:
    """16x2 character LCD on a PCF8574 I2C backpack.

    Pages rotate automatically so every channel is visible without buttons.
    Pass ``lcd`` to inject a stub in tests.
    """

    def __init__(
        self,
        address: int = 0x27,
        bus: int = 1,
        columns: int = 16,
        rows: int = 2,
        page_seconds: float = 4.0,
        lcd: Any = None,
    ) -> None:
        self.columns = columns
        self.rows = rows
        self.page_seconds = max(1.0, page_seconds)
        if lcd is None:
            from RPLCD.i2c import CharLCD

            lcd = CharLCD(
                i2c_expander="PCF8574",
                address=address,
                port=bus,
                cols=columns,
                rows=rows,
                charmap="A02",
                auto_linebreaks=False,
            )
            lcd.clear()
        self.lcd = lcd
        self._started = time.monotonic()

    def close(self) -> None:
        try:
            self.lcd.close()
        except Exception:  # pragma: no cover - hardware specific
            pass

    def show(
        self,
        reading: dict[str, Any],
        fix: dict[str, Any] | None = None,
        gps_status: str | None = None,
    ) -> None:
        pages = self._pages(reading, fix, gps_status)
        if not pages:
            pages = [["AERO-HUB", "waiting for data"]]
        elapsed = time.monotonic() - self._started
        page = pages[int(elapsed // self.page_seconds) % len(pages)]
        self._render(page)

    def _render(self, lines: list[str]) -> None:
        for row in range(min(len(lines), self.rows)):
            text = lines[row][: self.columns]
            self.lcd.cursor_pos = (row, 0)
            self.lcd.write_string(text.ljust(self.columns))

    def _pages(
        self,
        reading: dict[str, Any],
        fix: dict[str, Any] | None,
        gps_status: str | None,
    ) -> list[list[str]]:
        pages: list[list[str]] = []

        if reading.get("temperature") is not None or reading.get("pressure") is not None:
            pages.append(
                [
                    f"Temp {_fmt(reading.get('temperature'), '{:.1f}', 'C')}",
                    f"Pres {_fmt(reading.get('pressure'), '{:.0f}', 'hPa')}",
                ]
            )

        if reading.get("co_ppm") is not None or reading.get("mq135_estimated_ppm") is not None:
            pages.append(
                [
                    f"CO   {_fmt(reading.get('co_ppm'), '{:.1f}', 'ppm')}",
                    f"AQ   {_fmt(reading.get('mq135_estimated_ppm'), '{:.0f}', 'ppm')}",
                ]
            )

        if reading.get("dust_ug_m3") is not None or reading.get("dust_voltage") is not None:
            pages.append(
                [
                    f"Dust {_fmt(reading.get('dust_ug_m3'), '{:.1f}', 'ug/m3')}",
                    f"Vo   {_fmt(reading.get('dust_voltage'), '{:.2f}', 'V')}",
                ]
            )

        if fix and fix.get("latitude") is not None:
            lat = fix["latitude"]
            lon = fix["longitude"]
            sats = fix.get("satellites")
            pages.append(
                [
                    f"{abs(lat):.4f}{'N' if lat >= 0 else 'S'}",
                    f"{abs(lon):.4f}{'E' if lon >= 0 else 'W'} {int(sats) if sats else '?'}s",
                ]
            )
        elif gps_status:
            pages.append(["GPS", gps_status])

        return pages


def create_lcd() -> LcdDisplay | None:
    """Build an :class:`LcdDisplay` from the environment, or ``None`` if disabled."""
    if not _env_bool("LCD_ENABLED", False):
        return None
    try:
        return LcdDisplay(
            address=_env_int("LCD_I2C_ADDRESS", 0x27),
            bus=_env_int("LCD_I2C_BUS", 1),
            columns=_env_int("LCD_COLUMNS", 16),
            rows=_env_int("LCD_ROWS", 2),
            page_seconds=_env_float("LCD_PAGE_SECONDS", 4.0),
        )
    except Exception as exc:  # missing RPLCD, wrong address, I2C disabled
        logger.warning("LCD disabled: %s", exc)
        return None
