import math
import json
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import AppSetting, PollutionAlert, SensorReading, SensorStatus, SensorThreshold
from app.schemas import ReadingCreate

SENSOR_FIELDS = {
    "co": ("co_ppm", "CO", "ppm"),
    "mq135": ("mq135_raw", "MQ-135", "V"),
    "dust": ("dust_ug_m3", "Dust", "µg/m³"),
}
DEFAULT_THRESHOLDS = {
    "co": (9.0, 35.0),
    "mq135": (2.5, 4.0),
    "dust": (35.0, 150.0),
}
WHO_DAILY_GUIDELINES = {"pm2_5": 15.0, "pm10": 45.0}
CPCB_PM_BREAKPOINTS = {
    "pm2_5": ((0, 30, 0, 50), (30, 60, 50, 100), (60, 90, 100, 200),
              (90, 120, 200, 300), (120, 250, 300, 400), (250, 500, 400, 500)),
    "pm10": ((0, 50, 0, 50), (50, 100, 50, 100), (100, 250, 100, 200),
             (250, 350, 200, 300), (350, 430, 300, 400), (430, 600, 400, 500)),
}
CPCB_BANDS = (
    (50, "Good", "good"),
    (100, "Satisfactory", "satisfactory"),
    (200, "Moderate", "moderate"),
    (300, "Poor", "poor"),
    (400, "Very Poor", "very_poor"),
    (500, "Severe", "severe"),
)


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


def _distance_km(latitude: float, longitude: float, other_latitude: float, other_longitude: float) -> float:
    radius = 6371.0
    lat1, lat2 = math.radians(latitude), math.radians(other_latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(other_longitude - longitude)
    arc = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    arc = min(1.0, max(0.0, arc))
    return radius * 2 * math.atan2(math.sqrt(arc), math.sqrt(1 - arc))


def location_markers(db: Session, limit: int = 1000) -> list[dict]:
    rows = db.scalars(
        select(SensorReading)
        .where(SensorReading.latitude.is_not(None), SensorReading.longitude.is_not(None))
        .order_by(SensorReading.timestamp.desc(), SensorReading.id.desc())
        .limit(20000)
    ).all()
    sites: dict[tuple[str, float, float], SensorReading] = {}
    for row in rows:
        key = (row.location_name or "Unnamed site", round(row.latitude, 5), round(row.longitude, 5))
        sites.setdefault(key, row)
    return [
        {
            "location_name": row.location_name or "Unnamed site",
            "latitude": row.latitude,
            "longitude": row.longitude,
            "latest": reading_payload(row),
        }
        for row in list(sites.values())[:limit]
    ]


def assess_area(db: Session, latitude: float, longitude: float, radius_km: float) -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=24)
    lat_delta = radius_km / 110.574
    lon_delta = min(180.0, radius_km / max(111.32 * abs(math.cos(math.radians(latitude))), 0.01))
    south, north = max(-90, latitude - lat_delta), min(90, latitude + lat_delta)
    west, east = longitude - lon_delta, longitude + lon_delta
    spatial = [SensorReading.latitude.between(south, north)]
    if west < -180:
        longitude_filter = (
            (SensorReading.longitude >= west + 360) | (SensorReading.longitude <= east)
        )
    elif east > 180:
        longitude_filter = (
            (SensorReading.longitude >= west) | (SensorReading.longitude <= east - 360)
        )
    else:
        longitude_filter = SensorReading.longitude.between(west, east)
    spatial.append(longitude_filter)
    candidates = db.scalars(
        select(SensorReading)
        .where(
            and_(
                *spatial,
                SensorReading.timestamp >= start,
                SensorReading.timestamp <= now,
            )
        )
        .order_by(SensorReading.timestamp.desc(), SensorReading.id.desc())
        .limit(50000)
    ).all()
    nearby = [
        row for row in candidates
        if _distance_km(latitude, longitude, row.latitude, row.longitude) <= radius_km
    ]
    latest = nearby[0] if nearby else None
    sites: dict[tuple[str, float, float], SensorReading] = {}
    for row in nearby:
        key = (row.location_name or "Unnamed site", round(row.latitude, 5), round(row.longitude, 5))
        sites.setdefault(key, row)
    selected_sites = [
        {
            "location_name": row.location_name or "Unnamed site",
            "latitude": row.latitude,
            "longitude": row.longitude,
            "latest": reading_payload(row),
        }
        for row in sites.values()
    ]
    by_particle: dict[str, list[SensorReading]] = {"pm2_5": [], "pm10": []}
    for row in nearby:
        if row.dust_ug_m3 is not None and row.dust_particle_size in by_particle:
            by_particle[row.dust_particle_size].append(row)

    def sample_coverage(samples: list[SensorReading]) -> tuple[float, bool, int]:
        if not samples:
            return 0.0, False, 0
        timestamps = [
            sample.timestamp.replace(tzinfo=timezone.utc) if sample.timestamp.tzinfo is None else sample.timestamp
            for sample in samples
        ]
        oldest, newest = min(timestamps), max(timestamps)
        coverage = min(24.0, max(0.0, (newest - oldest).total_seconds() / 3600))
        fresh = now - newest <= timedelta(hours=1)
        covered_hours = len({timestamp.replace(minute=0, second=0, microsecond=0) for timestamp in timestamps})
        return coverage, fresh, covered_hours

    coverage_hours, _, _ = sample_coverage(nearby)
    warnings = []
    means = {}
    for size, name in (("pm2_5", "PM2.5"), ("pm10", "PM10")):
        samples = by_particle[size]
        pollutant_coverage, fresh, covered_hours = sample_coverage(samples)
        mean = sum(row.dust_ug_m3 for row in samples) / len(samples) if samples else None
        full_window = pollutant_coverage >= 23.9 and fresh and covered_hours >= 24
        means[size] = mean if full_window else None
        limit = WHO_DAILY_GUIDELINES[size]
        warnings.append({
            "authority": "WHO",
            "pollutant": name,
            "value": round(mean, 2) if mean is not None else None,
            "unit": "µg/m³",
            "guideline": limit,
            "status": ("exceeds" if mean > limit else "within") if mean is not None and full_window else "insufficient_data",
            "label": (
                "Above 2021 24-hour guideline" if mean is not None and mean > limit and full_window else
                "Within 2021 24-hour guideline" if mean is not None and full_window else
                f"Needs a calibrated sensor and complete hourly 24-hour window ({pollutant_coverage:.1f}h, {covered_hours}/24 hours)"
            ),
        })
        if mean is not None and full_window:
            warnings.append({
                "authority": "CPCB",
                "pollutant": f"{name} sub-index",
                "value": round(mean, 2),
                "unit": "µg/m³",
                "sub_index": cpcb_pm_subindex(mean, size),
                "status": "available",
                "label": "Pollutant sub-index only; not a station AQI",
            })
    co_samples = [row for row in nearby if row.co_ppm is not None]
    co_mean_mg = None
    co_coverage, co_fresh, co_covered_hours = sample_coverage(co_samples)
    if co_samples and co_coverage >= 23.9 and co_fresh and co_covered_hours >= 24:
        co_mean_mg = sum(
            row.co_ppm * 28.01 * ((row.pressure or 1013.25) / 10) / (8.314 * ((row.temperature or 25) + 273.15))
            for row in co_samples
        ) / len(co_samples)
    warnings.append({
        "authority": "WHO",
        "pollutant": "CO",
        "value": round(co_mean_mg, 2) if co_mean_mg is not None else None,
        "unit": "mg/m³",
        "guideline": 4.0,
        "status": ("exceeds" if co_mean_mg > 4.0 else "within") if co_mean_mg is not None else "insufficient_data",
        "label": (
            "Above 2021 24-hour guideline" if co_mean_mg is not None and co_mean_mg > 4.0 else
            "Within 2021 24-hour guideline" if co_mean_mg is not None else
            "Needs a full 24-hour CO measurement window"
        ),
    })
    warnings.append({
        "authority": "WMO",
        "pollutant": "Weather context",
        "value": None,
        "unit": "",
        "status": "forecast_unavailable",
        "label": "No WMO forecast feed is connected; local sensor readings are not an official WMO weather alert.",
    })
    return {
        "center": {"latitude": latitude, "longitude": longitude, "radius_km": radius_km},
        "locations": selected_sites,
        "latest": reading_payload(latest) if latest else None,
        "readings": [reading_payload(row) for row in reversed(nearby[:1000])],
        "sample_count_24h": len(nearby),
        "coverage_hours": round(coverage_hours, 1),
        "warnings": warnings,
    }


def get_thresholds(db: Session) -> dict[str, SensorThreshold]:
    rows = db.scalars(select(SensorThreshold)).all()
    existing = {row.sensor_name: row for row in rows}
    changed = False
    for key, (warning, critical) in DEFAULT_THRESHOLDS.items():
        if key not in existing:
            item = SensorThreshold(sensor_name=key, warning_threshold=warning, critical_threshold=critical)
            db.add(item)
            existing[key] = item
            changed = True
    if changed:
        db.commit()
    return existing


def air_quality_score(reading: SensorReading) -> int | None:
    values = []
    co = reading.co_ppm
    dust = reading.dust_ug_m3
    gas = reading.mq135_raw
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


def get_persisted_setting(db: Session, key: str, default):
    setting = db.get(AppSetting, key)
    return json.loads(setting.value) if setting else default


def set_persisted_setting(db: Session, key: str, value) -> None:
    db.merge(AppSetting(setting_key=key, value=json.dumps(value)))
    db.commit()


def reading_payload(reading: SensorReading) -> dict:
    score = air_quality_score(reading)
    return {
        "id": reading.id,
        "timestamp": reading.timestamp.isoformat(),
        "temperature": reading.temperature,
        "pressure": reading.pressure,
        "altitude": reading.altitude,
        "co_ppm": reading.co_ppm,
        "mq135_raw": reading.mq135_raw,
        "mq135_estimated_ppm": reading.mq135_estimated_ppm,
        "dust_voltage": reading.dust_voltage,
        "dust_ug_m3": reading.dust_ug_m3,
        "dust_particle_size": reading.dust_particle_size,
        "location_name": reading.location_name,
        "latitude": reading.latitude,
        "longitude": reading.longitude,
        "source": reading.source,
        "air_quality_score": score,
        "pollution_status": status_for_score(score),
    }


def save_reading(db: Session, data: ReadingCreate) -> SensorReading:
    values = data.model_dump()
    values["timestamp"] = values["timestamp"] or datetime.now(timezone.utc)
    reading = SensorReading(**values)
    db.add(reading)
    db.flush()

    seen = datetime.now(timezone.utc)
    sensor_map = {
        "BMP280": ("temperature", "pressure"),
        "MQ-7": ("co_ppm",),
        "MQ-135": ("mq135_raw", "mq135_estimated_ppm"),
        "Sharp dust": ("dust_voltage", "dust_ug_m3"),
    }
    for sensor_name, fields in sensor_map.items():
        if any(getattr(reading, field) is not None for field in fields):
            status = db.scalar(select(SensorStatus).where(SensorStatus.sensor_name == sensor_name))
            if status is None:
                status = SensorStatus(sensor_name=sensor_name, calibration_status="not calibrated")
                db.add(status)
            status.status = "online"
            status.last_seen = seen

    thresholds = get_thresholds(db)
    for key, (field, label, unit) in SENSOR_FIELDS.items():
        value = getattr(reading, field)
        if value is None:
            continue
        threshold = thresholds[key]
        if value >= threshold.critical_threshold:
            severity = "critical"
            limit = threshold.critical_threshold
        elif value >= threshold.warning_threshold:
            severity = "warning"
            limit = threshold.warning_threshold
        else:
            continue
        db.add(
            PollutionAlert(
                alert_type=label,
                severity=severity,
                message=f"{label} reading {value:g} {unit} exceeded the {severity} threshold ({limit:g} {unit}).",
                sensor_value=value,
                reading_id=reading.id,
            )
        )
    db.commit()
    db.refresh(reading)
    return reading


def simulated_reading(location: dict | None = None) -> ReadingCreate:
    now = datetime.now(timezone.utc)
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
