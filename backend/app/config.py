"""Environment-driven configuration for AERO-HUB.

Two deployment presets are supported:

``DATA_MODE=cloud``
    The Raspberry Pi posts readings to this API. The API stores them in
    MongoDB Atlas and pushes changes to browsers over WebSocket.

``DATA_MODE=direct``
    This API runs on the Raspberry Pi itself. It reads the sensors in-process,
    persists to a local file, and serves the dashboard over the LAN.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env regardless of the shell's current directory.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _text(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float | None = None) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _pair(latitude: float | None, longitude: float | None) -> tuple[float | None, float | None]:
    if latitude is None or longitude is None:
        return None, None
    return latitude, longitude


@dataclass(frozen=True)
class Settings:
    data_mode: str
    storage_backend: str
    storage_path: str
    file_max_readings: int

    mongodb_uri: str
    mongodb_db: str
    mongodb_change_stream: bool
    mongodb_timeout_ms: int
    reading_retention_days: int

    sensor_source: str
    hardware_interval_seconds: float
    demo_mode: bool
    demo_interval_seconds: float
    device_api_key: str | None

    device_location_name: str | None
    device_latitude: float | None
    device_longitude: float | None
    dust_particle_size: str

    demo_location_name: str | None
    demo_latitude: float | None
    demo_longitude: float | None

    frontend_origins: tuple[str, ...]

    @property
    def demo_location(self) -> dict:
        return {
            "location_name": self.demo_location_name,
            "latitude": self.demo_latitude,
            "longitude": self.demo_longitude,
        }

    @property
    def device_location(self) -> dict:
        return {
            "location_name": self.device_location_name,
            "latitude": self.device_latitude,
            "longitude": self.device_longitude,
        }

    @property
    def change_stream_active(self) -> bool:
        return self.storage_backend == "mongodb" and self.mongodb_change_stream

    def public_summary(self) -> dict:
        return {
            "data_mode": self.data_mode,
            "storage_backend": self.storage_backend,
            "sensor_source": self.sensor_source,
            "change_stream": self.change_stream_active,
            "retention_days": self.reading_retention_days,
            "server_time": datetime.now().astimezone().isoformat(),
        }


def get_settings() -> Settings:
    data_mode = _text("DATA_MODE", "cloud").lower()
    if data_mode not in {"cloud", "direct"}:
        data_mode = "cloud"

    default_storage = "mongodb" if data_mode == "cloud" else "file"
    storage_backend = _text("STORAGE_BACKEND", default_storage).lower()
    if storage_backend not in {"mongodb", "file", "memory"}:
        storage_backend = default_storage

    default_source = "external" if data_mode == "cloud" else "hardware"
    sensor_source = _text("SENSOR_SOURCE", default_source).lower()
    if sensor_source not in {"external", "hardware"}:
        sensor_source = default_source

    dust_particle_size = _text("DUST_PARTICLE_SIZE", "unknown").lower()
    if dust_particle_size not in {"unknown", "pm2_5", "pm10"}:
        dust_particle_size = "unknown"

    device_latitude, device_longitude = _pair(
        _float("DEVICE_LATITUDE"), _float("DEVICE_LONGITUDE")
    )
    device_name = _text("DEVICE_LOCATION_NAME") or None
    if device_name is None:
        device_latitude = device_longitude = None

    demo_latitude, demo_longitude = _pair(
        _float("DEMO_LATITUDE"), _float("DEMO_LONGITUDE")
    )
    demo_name = _text("DEMO_LOCATION_NAME") or None
    if demo_name is None:
        demo_latitude = demo_longitude = None

    origins = tuple(
        origin.strip()
        for origin in _text("FRONTEND_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    )

    return Settings(
        data_mode=data_mode,
        storage_backend=storage_backend,
        storage_path=_text("STORAGE_PATH", "./data/airsense.jsonl"),
        file_max_readings=max(1000, _int("FILE_MAX_READINGS", 100000)),
        mongodb_uri=_text("MONGODB_URI"),
        mongodb_db=_text("MONGODB_DB", "airsense"),
        mongodb_change_stream=_bool("MONGODB_CHANGE_STREAM", True),
        mongodb_timeout_ms=_int("MONGODB_TIMEOUT_MS", 10000),
        reading_retention_days=max(0, _int("READING_RETENTION_DAYS", 0)),
        sensor_source=sensor_source,
        hardware_interval_seconds=max(1.0, _float("HARDWARE_INTERVAL_SECONDS", 5.0) or 5.0),
        demo_mode=_bool("DEMO_MODE", False),
        demo_interval_seconds=max(1.0, _float("DEMO_INTERVAL_SECONDS", 5.0) or 5.0),
        device_api_key=_text("DEVICE_API_KEY") or None,
        device_location_name=device_name,
        device_latitude=device_latitude,
        device_longitude=device_longitude,
        dust_particle_size=dust_particle_size,
        demo_location_name=demo_name,
        demo_latitude=demo_latitude,
        demo_longitude=demo_longitude,
        frontend_origins=origins or ("http://localhost:5173",),
    )
