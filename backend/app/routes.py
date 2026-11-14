from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.config import Settings
from app.schemas import DemoLocation, DemoSetting, ReadingCreate, ThresholdUpdate
from app.services import (
    RecentReadingIds,
    alert_payload,
    assess_area,
    build_statuses,
    ingest_reading,
    location_markers,
    reading_payload,
)
from app.store import Store

router = APIRouter(prefix="/api")


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_runtime_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_recent_ids(request: Request) -> RecentReadingIds:
    return request.app.state.recent_ids


async def require_device_key(
    request: Request,
    settings: Settings = Depends(get_runtime_settings),
) -> None:
    """Optional shared secret for hardware ingestion.

    Leave DEVICE_API_KEY empty for a trusted lab network. When it is set, the
    Raspberry Pi must send the same value in the X-API-Key header.
    """
    if not settings.device_api_key:
        return
    supplied = request.headers.get("x-api-key", "")
    if not secrets.compare_digest(supplied, settings.device_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing device API key")


@router.post("/sensors/readings", status_code=201)
async def create_reading(
    payload: ReadingCreate,
    store: Store = Depends(get_store),
    recent_ids: RecentReadingIds = Depends(get_recent_ids),
    _: None = Depends(require_device_key),
):
    reading = await ingest_reading(store, payload, recent_ids=recent_ids)
    return reading_payload(reading)


@router.post("/sensors/manual", status_code=201)
async def create_manual_reading(
    payload: ReadingCreate,
    store: Store = Depends(get_store),
    recent_ids: RecentReadingIds = Depends(get_recent_ids),
):
    manual = payload.model_copy(update={"source": "manual"})
    reading = await ingest_reading(store, manual, recent_ids=recent_ids)
    return reading_payload(reading)


@router.get("/sensors/latest")
async def latest_reading(store: Store = Depends(get_store)):
    reading = await store.get_latest()
    return reading_payload(reading) if reading else None


@router.get("/sensors/locations")
async def sensor_locations(
    limit: int = Query(default=1000, ge=1, le=5000),
    store: Store = Depends(get_store),
):
    return await location_markers(store, limit=limit)


@router.get("/sensors/area")
async def sensor_area(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=5, ge=0.1, le=50),
    store: Store = Depends(get_store),
):
    return await assess_area(store, latitude, longitude, radius_km)


def _downsample(rows: list[dict], max_points: int | None) -> list[dict]:
    """Return evenly spaced rows for charts without changing statistics."""
    if not max_points or len(rows) <= max_points:
        return rows
    if max_points == 1:
        return [rows[-1]]
    step = (len(rows) - 1) / (max_points - 1)
    return [rows[round(index * step)] for index in range(max_points)]


@router.get("/sensors/history")
async def reading_history(
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=1000, ge=1, le=50000),
    max_points: int | None = Query(default=None, ge=1, le=50000),
    source: str | None = None,
    store: Store = Depends(get_store),
):
    rows = await store.list_readings(start=start, end=end, limit=limit, source=source)
    return [reading_payload(row) for row in _downsample(rows, max_points)]


@router.get("/sensors/statistics")
async def reading_statistics(
    start: datetime | None = None,
    end: datetime | None = None,
    store: Store = Depends(get_store),
):
    return await store.statistics(start=start, end=end)


@router.get("/sensors/status")
async def sensor_status(store: Store = Depends(get_store)):
    return await build_statuses(store)


@router.get("/alerts")
async def get_alerts(
    limit: int = Query(default=100, ge=1, le=1000),
    store: Store = Depends(get_store),
):
    return [alert_payload(alert) for alert in await store.list_alerts(limit=limit)]


@router.get("/thresholds")
async def read_thresholds(store: Store = Depends(get_store)):
    return await store.get_thresholds()


@router.put("/thresholds/{sensor_name}")
async def update_threshold(
    sensor_name: str,
    payload: ThresholdUpdate,
    store: Store = Depends(get_store),
):
    if sensor_name not in ("co", "mq135", "dust"):
        raise HTTPException(status_code=404, detail="Unknown threshold sensor")
    result = await store.set_threshold(
        sensor_name, payload.warning_threshold, payload.critical_threshold
    )
    return {"sensor_name": sensor_name, **result}


@router.get("/settings/demo")
async def get_demo_setting(
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_runtime_settings),
):
    return {"enabled": await store.get_setting("demo_enabled", settings.demo_mode)}


@router.put("/settings/demo")
async def set_demo_setting(
    payload: DemoSetting,
    store: Store = Depends(get_store),
):
    await store.set_setting("demo_enabled", payload.enabled)
    return {"enabled": payload.enabled}


@router.get("/settings/demo-location")
async def get_demo_location(
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_runtime_settings),
):
    return await store.get_setting("demo_location", settings.demo_location)


@router.put("/settings/demo-location")
async def set_demo_location(payload: DemoLocation, store: Store = Depends(get_store)):
    location = payload.model_dump()
    await store.set_setting("demo_location", location)
    return location


@router.get("/health")
async def health(
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_runtime_settings),
):
    return await health_report(store, settings)


async def health_report(store: Store, settings: Settings) -> dict:
    try:
        if hasattr(store, "health"):
            info = await store.health()
        else:
            info = {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Storage unavailable: {exc}") from exc
    return {
        "status": "ok",
        "database": info,
        "data_mode": settings.data_mode,
        "sensor_source": settings.sensor_source,
    }


@router.get("/config")
async def runtime_config(settings: Settings = Depends(get_runtime_settings)):
    return settings.public_summary()
