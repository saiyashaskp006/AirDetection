"""Domain logic shared by the REST API, WebSocket watcher and demo loop."""

from __future__ import annotations

import math
import random
from collections import deque
from datetime import timedelta

from app.defaults import (
    KNOWN_SENSORS,
    SENSOR_FIELDS,
    SENSOR_PRESENCE,
    WHO_DAILY_GUIDELINES,
)
from app.geo import bounding_box, distance_km
from app.schemas import ReadingCreate
from app.store import Store
from app.timeutil import as_utc, iso, utc_now
from app.websocket import manager

CPCB_PM_BREAKPOINTS = {
    "pm2_5": (
        (0, 30, 0, 50),
        (30, 60, 50, 100),
        (60, 90, 100, 200),
        (90, 120, 200, 300),
        (120, 250, 300, 400),
        (250, 500, 400, 500),
    ),
    "pm10": (
        (0, 50, 0, 50),
        (50, 100, 50, 100),
        (100, 250, 100, 200),
        (250, 350, 200, 300),
        (350, 430, 300, 400),
        (430, 600, 400, 500),
    ),
}
CPCB_BANDS = (
    (50, "Good", "good"),
    (100, "Satisfactory", "satisfactory"),
    (200, "Moderate", "moderate"),
    (300, "Poor", "poor"),
    (400, "Very Poor", "very_poor"),
    (500, "Severe", "severe"),
)


class RecentReadingIds:
    """Allow each reading to be broadcast exactly once per process.

    The MongoDB change stream also sees writes made by this API. Both the HTTP
    route and the watcher call :meth:`first`; whichever path arrives first sends
    the WebSocket message and the other path skips it. Readings written by other
    processes are still delivered because their IDs have not been seen here.
    """

    def __init__(self, maxlen: int = 2000) -> None:
        self._order: deque[str] = deque()
        self._ids: set[str] = set()
        self._maxlen = maxlen

    def first(self, reading_id: str | int) -> bool:
        key = str(reading_id)
        if key in self._ids:
            return False
        self._ids.add(key)
        self._order.append(key)
        while len(self._order) > self._maxlen:
            old = self._order.popleft()
            self._ids.discard(old)
        return True


def cpcb_pm_subindex(value: float, particle_size: str) -> dict:
    for low, high, index_low, index_high in CPCB_PM_BREAKPOINTS[particle_size]:
        if value <= high or high == CPCB_PM_BREAKPOINTS[particle_size][-1][1]:
            subindex = round((index_high - index_low) / (high - low) * (value - low) + index_low)
            if index_low == 400:
                subindex = max(401, subindex)
            subindex = min(500, subindex)
            band = next(name for boundary, name, _ in CPCB_BANDS if subindex <= boundary)
            severity = next(key for boundary, _, key in CPCB_BANDS if subindex <= boundary)
            return {"value": max(0, subindex), "category": band, "severity": severity}
    return {"value": 500, "category": "Severe", "severity": "severe"}


def air_quality_score(reading: dict) -> int | None:
    values = []
    co = reading.get("co_ppm")
    dust = reading.get("dust_ug_m3")
    gas = reading.get("mq135_raw")
    if co is not None:
        values.append(min(co / 35.0, 1.0))
    if dust is not None:
        values.append(min(dust / 150.0, 1.0))
    if gas is not None:
        values.append(min(gas / 4.0, 1.0))
    if not values:
        return None
    return round(max(0, 100 - (sum(values) / len(values)) * 100))


def status_for_score(score: int | None) -> str:
    if score is None:
        return "No data"
    if score >= 80:
        return "Good"
    if score >= 60:
        return "Moderate"
    if score >= 35:
        return "Poor"
    return "Very Poor"


def reading_payload(reading: dict) -> dict:
    score = air_quality_score(reading)
    return {
        "id": reading.get("id"),
        "timestamp": iso(reading.get("timestamp")),
        "temperature": reading.get("temperature"),
        "pressure": reading.get("pressure"),
        "altitude": reading.get("altitude"),
        "co_ppm": reading.get("co_ppm"),
        "mq135_raw": reading.get("mq135_raw"),
        "mq135_estimated_ppm": reading.get("mq135_estimated_ppm"),
        "dust_voltage": reading.get("dust_voltage"),
        "dust_ug_m3": reading.get("dust_ug_m3"),
        "dust_particle_size": reading.get("dust_particle_size"),
        "location_name": reading.get("location_name"),
        "latitude": reading.get("latitude"),
        "longitude": reading.get("longitude"),
        "source": reading.get("source"),
        "air_quality_score": score,
        "pollution_status": status_for_score(score),
    }


def alert_payload(alert: dict) -> dict:
    return {
        "id": alert.get("id"),
        "alert_type": alert.get("alert_type"),
        "severity": alert.get("severity"),
        "message": alert.get("message"),
        "timestamp": iso(alert.get("timestamp")),
        "sensor_value": alert.get("sensor_value"),
        "reading_id": alert.get("reading_id"),
    }


async def _mark_sensors_seen(store: Store, reading: dict) -> None:
    names = [
        name
        for name, fields in SENSOR_PRESENCE.items()
        if any(reading.get(field) is not None for field in fields)
    ]
    if names:
        await store.mark_sensors_seen(names, utc_now())


async def _process_alerts(store: Store, reading: dict) -> None:
    # The atomic claim makes sure a reading that is both returned by the HTTP
    # route and observed by the change stream only creates one alert batch.
    if not await store.claim_reading_for_alerts(reading.get("id")):
        return
    thresholds = await store.get_thresholds()
    alerts: list[dict] = []
    for key, (field, label, unit) in SENSOR_FIELDS.items():
        value = reading.get(field)
        if value is None:
            continue
        threshold = thresholds.get(key) or {}
        warning = threshold.get("warning_threshold")
        critical = threshold.get("critical_threshold")
        if critical is not None and value >= critical:
            severity, limit = "critical", critical
        elif warning is not None and value >= warning:
            severity, limit = "warning", warning
        else:
            continue
        alerts.append(
            {
                "alert_type": label,
                "severity": severity,
                "message": (
                    f"{label} reading {value:g} {unit} exceeded the {severity} "
                    f"threshold ({limit:g} {unit})."
                ),
                "timestamp": utc_now(),
                "sensor_value": value,
                "reading_id": reading.get("id"),
            }
        )
    if alerts:
        await store.insert_alerts(alerts)


async def ingest_reading(
    store: Store,
    data: ReadingCreate,
    *,
    recent_ids: RecentReadingIds | None = None,
    broadcast: bool = True,
) -> dict:
    values = {key: value for key, value in data.model_dump().items() if value is not None}
    values["timestamp"] = as_utc(values.get("timestamp")) or utc_now()
    values["created_at"] = utc_now()
    reading = await store.insert_reading(values)
    await _mark_sensors_seen(store, reading)
    await _process_alerts(store, reading)
    if broadcast and (recent_ids is None or recent_ids.first(reading["id"])):
        await manager.broadcast({"type": "reading", "data": reading_payload(reading)})
    return reading


async def handle_watched_reading(
    store: Store,
    reading: dict,
    recent_ids: RecentReadingIds | None = None,
) -> None:
    """Handle a reading observed by the MongoDB change stream."""
    await _mark_sensors_seen(store, reading)
    await _process_alerts(store, reading)
    if recent_ids is not None and not recent_ids.first(reading.get("id")):
        return
    await manager.broadcast({"type": "reading", "data": reading_payload(reading)})


def simulated_reading(location: dict | None = None) -> ReadingCreate:
    now = utc_now()
    hour = now.hour + now.minute / 60
    return ReadingCreate(
        timestamp=now,
        temperature=round(21 + 5 * math.sin(hour / 24 * math.tau) + random.uniform(-0.4, 0.4), 1),
        pressure=round(1012 + random.uniform(-4, 4), 1),
        altitude=round(110 + random.uniform(-1, 1), 1),
        co_ppm=round(max(0.2, random.gauss(4.5, 2.2)), 2),
        mq135_raw=round(min(4.9, max(0.15, random.gauss(1.25, 0.45))), 3),
        dust_voltage=round(random.uniform(0.35, 1.35), 3),
        dust_ug_m3=round(max(2, random.gauss(24, 14)), 1),
        dust_particle_size="unknown",
        source="simulation",
        location_name=(location or {}).get("location_name"),
        latitude=(location or {}).get("latitude"),
        longitude=(location or {}).get("longitude"),
    )


async def build_statuses(store: Store) -> list[dict]:
    statuses = await store.statuses()
    thresholds = await store.get_thresholds()
    latest = await store.get_latest()
    known = {row.get("sensor_name") for row in statuses}
    latest_timestamp = latest.get("timestamp") if latest else None
    for sensor_name in KNOWN_SENSORS:
        if sensor_name not in known:
            # After a file-store restart the status collection is empty. Derive
            # the last-seen time from the latest reading when possible.
            reported = latest and any(
                latest.get(field) is not None for field in SENSOR_PRESENCE[sensor_name]
            )
            statuses.append(
                {
                    "sensor_name": sensor_name,
                    "status": "offline",
                    "last_seen": latest_timestamp if reported else None,
                    "calibration_status": "not calibrated",
                }
            )

    now = utc_now()
    result = []
    for row in statuses:
        last_seen = as_utc(row.get("last_seen"))
        online = last_seen is not None and (now - last_seen) <= timedelta(seconds=30)
        threshold_key = {
            "MQ-7": "co",
            "MQ-135": "mq135",
            "Sharp dust": "dust",
        }.get(row.get("sensor_name"))
        threshold = thresholds.get(threshold_key) if threshold_key else None
        latest_value = None
        if latest:
            for field in SENSOR_PRESENCE.get(row.get("sensor_name"), ()):
                if latest.get(field) is not None:
                    latest_value = latest[field]
                    break
        result.append(
            {
                "sensor_name": row.get("sensor_name"),
                "status": "online" if online else "offline",
                "last_seen": iso(last_seen),
                "calibration_status": row.get("calibration_status") or "not calibrated",
                "latest_reading": latest_value,
                "thresholds": (
                    {
                        "warning_threshold": threshold.get("warning_threshold"),
                        "critical_threshold": threshold.get("critical_threshold"),
                    }
                    if threshold
                    else None
                ),
            }
        )
    return result


async def location_markers(store: Store, limit: int = 1000) -> list[dict]:
    rows = await store.list_locations(limit=limit)
    return [
        {
            "location_name": row.get("location_name") or "Unnamed site",
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "latest": reading_payload(row),
        }
        for row in rows
    ]


async def assess_area(store: Store, latitude: float, longitude: float, radius_km: float) -> dict:
    now = utc_now()
    start = now - timedelta(hours=24)
    south, north, longitude_ranges = bounding_box(latitude, longitude, radius_km)
    candidates = await store.area_candidates(
        start=start,
        end=now,
        south=south,
        north=north,
        longitude_ranges=longitude_ranges,
    )
    nearby = [
        row
        for row in candidates
        if row.get("latitude") is not None
        and row.get("longitude") is not None
        and distance_km(latitude, longitude, row["latitude"], row["longitude"]) <= radius_km
    ]
    latest = nearby[0] if nearby else None
    sites: dict[tuple[str, float, float], dict] = {}
    for row in nearby:
        key = (
            row.get("location_name") or "Unnamed site",
            round(float(row["latitude"]), 5),
            round(float(row["longitude"]), 5),
        )
        sites.setdefault(key, row)
    selected_sites = [
        {
            "location_name": row.get("location_name") or "Unnamed site",
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "latest": reading_payload(row),
        }
        for row in sites.values()
    ]
    by_particle: dict[str, list[dict]] = {"pm2_5": [], "pm10": []}
    for row in nearby:
        if row.get("dust_ug_m3") is not None and row.get("dust_particle_size") in by_particle:
            by_particle[row["dust_particle_size"]].append(row)

    def sample_coverage(samples: list[dict]) -> tuple[float, bool, int]:
        if not samples:
            return 0.0, False, 0
        timestamps = [as_utc(sample.get("timestamp")) for sample in samples if sample.get("timestamp")]
        if not timestamps:
            return 0.0, False, 0
        oldest, newest = min(timestamps), max(timestamps)
        coverage = min(24.0, max(0.0, (newest - oldest).total_seconds() / 3600))
        fresh = now - newest <= timedelta(hours=1)
        covered_hours = len(
            {timestamp.replace(minute=0, second=0, microsecond=0) for timestamp in timestamps}
        )
        return coverage, fresh, covered_hours

    coverage_hours, _, _ = sample_coverage(nearby)
    warnings = []
    means = {}
    for size, name in (("pm2_5", "PM2.5"), ("pm10", "PM10")):
        samples = by_particle[size]
        pollutant_coverage, fresh, covered_hours = sample_coverage(samples)
        mean = (
            sum(row["dust_ug_m3"] for row in samples) / len(samples) if samples else None
        )
        full_window = pollutant_coverage >= 23.9 and fresh and covered_hours >= 24
        means[size] = mean if full_window else None
        limit = WHO_DAILY_GUIDELINES[size]
        warnings.append(
            {
                "authority": "WHO",
                "pollutant": name,
                "value": round(mean, 2) if mean is not None else None,
                "unit": "µg/m³",
                "guideline": limit,
                "status": (
                    ("exceeds" if mean > limit else "within")
                    if mean is not None and full_window
                    else "insufficient_data"
                ),
                "label": (
                    "Above 2021 24-hour guideline"
                    if mean is not None and mean > limit and full_window
                    else "Within 2021 24-hour guideline"
                    if mean is not None and full_window
                    else (
                        "Needs a calibrated sensor and complete hourly 24-hour window "
                        f"({pollutant_coverage:.1f}h, {covered_hours}/24 hours)"
                    )
                ),
            }
        )
        if mean is not None and full_window:
            warnings.append(
                {
                    "authority": "CPCB",
                    "pollutant": f"{name} sub-index",
                    "value": round(mean, 2),
                    "unit": "µg/m³",
                    "sub_index": cpcb_pm_subindex(mean, size),
                    "status": "available",
                    "label": "Pollutant sub-index only; not a station AQI",
                }
            )
    co_samples = [row for row in nearby if row.get("co_ppm") is not None]
    co_mean_mg = None
    co_coverage, co_fresh, co_covered_hours = sample_coverage(co_samples)
    if co_samples and co_coverage >= 23.9 and co_fresh and co_covered_hours >= 24:
        co_mean_mg = sum(
            row["co_ppm"]
            * 28.01
            * ((row.get("pressure") or 1013.25) / 10)
            / (8.314 * ((row.get("temperature") or 25) + 273.15))
            for row in co_samples
        ) / len(co_samples)
    warnings.append(
        {
            "authority": "WHO",
            "pollutant": "CO",
            "value": round(co_mean_mg, 2) if co_mean_mg is not None else None,
            "unit": "mg/m³",
            "guideline": 4.0,
            "status": (
                ("exceeds" if co_mean_mg > 4.0 else "within")
                if co_mean_mg is not None
                else "insufficient_data"
            ),
            "label": (
                "Above 2021 24-hour guideline"
                if co_mean_mg is not None and co_mean_mg > 4.0
                else "Within 2021 24-hour guideline"
                if co_mean_mg is not None
                else "Needs a full 24-hour CO measurement window"
            ),
        }
    )
    warnings.append(
        {
            "authority": "WMO",
            "pollutant": "Weather context",
            "value": None,
            "unit": "",
            "status": "forecast_unavailable",
            "label": (
                "No WMO forecast feed is connected; local sensor readings are not "
                "an official WMO weather alert."
            ),
        }
    )
    return {
        "center": {"latitude": latitude, "longitude": longitude, "radius_km": radius_km},
        "locations": selected_sites,
        "latest": reading_payload(latest) if latest else None,
        "readings": [reading_payload(row) for row in reversed(nearby[:1000])],
        "sample_count_24h": len(nearby),
        "coverage_hours": round(coverage_hours, 1),
        "warnings": warnings,
    }


__all__ = [
    "RecentReadingIds",
    "alert_payload",
    "assess_area",
    "build_statuses",
    "ingest_reading",
    "location_markers",
    "reading_payload",
    "simulated_reading",
]
