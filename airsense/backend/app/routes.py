import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PollutionAlert, SensorReading, SensorStatus, SensorThreshold
from app.schemas import DemoLocation, DemoSetting, ReadingCreate, ReadingResponse, ThresholdUpdate
from app.services import (
    assess_area,
    get_persisted_setting,
    get_thresholds,
    location_markers,
    reading_payload,
    save_reading,
    set_persisted_setting,
)
from app.websocket import manager

router = APIRouter(prefix="/api")
demo_mode_default = os.getenv("DEMO_MODE", "false").lower() == "true"
demo_location_settings = DemoLocation(
    location_name=os.getenv("DEMO_LOCATION_NAME") or None,
    latitude=float(os.environ["DEMO_LATITUDE"]) if os.getenv("DEMO_LATITUDE") else None,
    longitude=float(os.environ["DEMO_LONGITUDE"]) if os.getenv("DEMO_LONGITUDE") else None,
).model_dump()


@router.post("/sensors/readings", response_model=ReadingResponse, status_code=201)
async def create_reading(payload: ReadingCreate, db: Session = Depends(get_db)):
    reading = save_reading(db, payload)
    await manager.broadcast({"type": "reading", "data": reading_payload(reading)})
    return reading


@router.post("/sensors/manual", response_model=ReadingResponse, status_code=201)
async def create_manual_reading(payload: ReadingCreate, db: Session = Depends(get_db)):
    manual = payload.model_copy(update={"source": "manual"})
    reading = save_reading(db, manual)
    await manager.broadcast({"type": "reading", "data": reading_payload(reading)})
    return reading


@router.get("/sensors/latest")
def latest_reading(db: Session = Depends(get_db)):
    reading = db.scalar(select(SensorReading).order_by(SensorReading.timestamp.desc(), SensorReading.id.desc()))
    return reading_payload(reading) if reading else None


@router.get("/sensors/locations")
def sensor_locations(limit: int = Query(default=1000, ge=1, le=5000), db: Session = Depends(get_db)):
    return location_markers(db, limit=limit)


@router.get("/sensors/area")
def sensor_area(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=5, ge=0.1, le=50),
    db: Session = Depends(get_db),
):
    return assess_area(db, latitude, longitude, radius_km)


@router.get("/sensors/history", response_model=list[ReadingResponse])
def reading_history(
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=1000, ge=1, le=50000),
    source: str | None = None,
    db: Session = Depends(get_db),
):
    query = select(SensorReading).order_by(SensorReading.timestamp.desc(), SensorReading.id.desc()).limit(limit)
    if start:
        query = query.where(SensorReading.timestamp >= start)
    if end:
        query = query.where(SensorReading.timestamp <= end)
    if source:
        query = query.where(SensorReading.source == source)
    return list(reversed(db.scalars(query).all()))


@router.get("/sensors/statistics")
def reading_statistics(
    start: datetime | None = None, end: datetime | None = None, db: Session = Depends(get_db)
):
    fields = ("temperature", "pressure", "co_ppm", "mq135_raw", "dust_ug_m3")
    query = select(SensorReading)
    if start:
        query = query.where(SensorReading.timestamp >= start)
    if end:
        query = query.where(SensorReading.timestamp <= end)
    result = {}
    filtered = query.subquery()
    for name in fields:
        column = filtered.c[name]
        minimum, maximum, average, count = db.execute(
            select(func.min(column), func.max(column), func.avg(column), func.count(column)).select_from(filtered)
        ).one()
        result[name] = {
            "min": minimum,
            "max": maximum,
            "average": average,
            "count": count,
        }
    return result


@router.get("/sensors/status")
def sensor_status(db: Session = Depends(get_db)):
    statuses = db.scalars(select(SensorStatus).order_by(SensorStatus.sensor_name)).all()
    threshold_rows = get_thresholds(db)
    latest = db.scalar(select(SensorReading).order_by(SensorReading.timestamp.desc(), SensorReading.id.desc()))
    known = {row.sensor_name for row in statuses}
    for sensor_name in ("BMP280", "MQ-7", "MQ-135", "Sharp dust"):
        if sensor_name not in known:
            statuses.append(SensorStatus(sensor_name=sensor_name, status="offline", calibration_status="not calibrated"))
    return [
        {
            "sensor_name": row.sensor_name,
            "status": (
                "online"
                if row.last_seen
                and datetime.now(timezone.utc)
                - (
                    row.last_seen.replace(tzinfo=timezone.utc)
                    if row.last_seen.tzinfo is None
                    else row.last_seen
                )
                <= timedelta(seconds=30)
                else "offline"
            ),
            "last_seen": row.last_seen,
            "calibration_status": row.calibration_status,
            "latest_reading": next(
                (
                    getattr(latest, field)
                    for field in {
                        "BMP280": ("temperature",),
                        "MQ-7": ("co_ppm",),
                        "MQ-135": ("mq135_raw",),
                        "Sharp dust": ("dust_ug_m3", "dust_voltage"),
                    }.get(row.sensor_name, ())
                    if getattr(latest, field) is not None
                ),
                None,
            ) if latest else None,
            "thresholds": (
                {
                    "warning_threshold": threshold_rows["co"].warning_threshold,
                    "critical_threshold": threshold_rows["co"].critical_threshold,
                } if row.sensor_name == "MQ-7" else
                {
                    "warning_threshold": threshold_rows["mq135"].warning_threshold,
                    "critical_threshold": threshold_rows["mq135"].critical_threshold,
                } if row.sensor_name == "MQ-135" else
                {
                    "warning_threshold": threshold_rows["dust"].warning_threshold,
                    "critical_threshold": threshold_rows["dust"].critical_threshold,
                } if row.sensor_name == "Sharp dust" else None
            ),
        }
        for row in statuses
    ]


@router.get("/alerts")
def get_alerts(limit: int = Query(default=100, ge=1, le=1000), db: Session = Depends(get_db)):
    return db.scalars(select(PollutionAlert).order_by(PollutionAlert.timestamp.desc()).limit(limit)).all()


@router.get("/thresholds")
def read_thresholds(db: Session = Depends(get_db)):
    return {
        row.sensor_name: {
            "warning_threshold": row.warning_threshold,
            "critical_threshold": row.critical_threshold,
        }
        for row in get_thresholds(db).values()
    }


@router.put("/thresholds/{sensor_name}")
def update_threshold(sensor_name: str, payload: ThresholdUpdate, db: Session = Depends(get_db)):
    if sensor_name not in ("co", "mq135", "dust"):
        raise HTTPException(status_code=404, detail="Unknown threshold sensor")
    row = get_thresholds(db)[sensor_name]
    row.warning_threshold = payload.warning_threshold
    row.critical_threshold = payload.critical_threshold
    db.commit()
    return {"sensor_name": sensor_name, **payload.model_dump()}


@router.get("/settings/demo")
def get_demo_setting(db: Session = Depends(get_db)):
    return {"enabled": get_persisted_setting(db, "demo_enabled", demo_mode_default)}


@router.put("/settings/demo")
def set_demo_setting(payload: DemoSetting, db: Session = Depends(get_db)):
    set_persisted_setting(db, "demo_enabled", payload.enabled)
    return {"enabled": payload.enabled}


@router.get("/settings/demo-location")
def get_demo_location(db: Session = Depends(get_db)):
    return get_persisted_setting(db, "demo_location", demo_location_settings)


@router.put("/settings/demo-location")
def set_demo_location(payload: DemoLocation, db: Session = Depends(get_db)):
    location = payload.model_dump()
    set_persisted_setting(db, "demo_location", location)
    return location
