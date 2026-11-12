from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.hardware import HardwareReader
from app.routes import health_report, router
from app.schemas import ReadingCreate
from app.services import (
    RecentReadingIds,
    handle_watched_reading,
    ingest_reading,
    reading_payload,
    simulated_reading,
)
from app.store import create_store
from app.websocket import manager

try:  # pymongo ships with motor, but the file backend does not need it.
    from pymongo.errors import PyMongoError
except ImportError:  # pragma: no cover - only when motor is not installed
    PyMongoError = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("aerohub")

settings = get_settings()


async def demo_loop(app: FastAPI) -> None:
    store = app.state.store
    while True:
        try:
            enabled = await store.get_setting("demo_enabled", settings.demo_mode)
            if enabled:
                location = await store.get_setting("demo_location", settings.demo_location)
                await ingest_reading(
                    store,
                    simulated_reading(location),
                    recent_ids=app.state.recent_ids,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Could not save or broadcast a simulated sensor reading.")
        await asyncio.sleep(settings.demo_interval_seconds)


async def hardware_loop(app: FastAPI) -> None:
    store = app.state.store
    try:
        reader = await asyncio.to_thread(HardwareReader, settings)
    except Exception:
        logger.exception(
            "Direct hardware mode is enabled but the sensors could not be opened. "
            "Check ADC_BACKEND, I2C/SPI, wiring and the Raspberry Pi packages."
        )
        return

    logger.info(
        "Reading Raspberry Pi sensors every %ss (direct mode).",
        settings.hardware_interval_seconds,
    )
    try:
        while True:
            try:
                payload = await asyncio.to_thread(reader.read)
                if payload:
                    await ingest_reading(
                        store,
                        ReadingCreate(**payload),
                        recent_ids=app.state.recent_ids,
                    )
                else:
                    logger.error("No sensor readings available; nothing was saved.")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Sensor cycle failed.")
            await asyncio.sleep(settings.hardware_interval_seconds)
    finally:
        await asyncio.to_thread(reader.close)


async def change_stream_loop(app: FastAPI) -> None:
    """Broadcast readings inserted by any process, including direct DB writers."""
    if not settings.change_stream_active:
        return
    store = app.state.store
    async for reading in store.watch_readings():
        try:
            await handle_watched_reading(store, reading, app.state.recent_ids)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Could not process a MongoDB change stream reading.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = create_store(settings)
    try:
        await store.connect()
        await store.ensure_ready()
    except Exception:
        logger.exception(
            "Storage startup failed. Check backend/.env, the MongoDB URI and the "
            "Atlas Network Access list. You can run with STORAGE_BACKEND=memory "
            "for a quick local test."
        )
        raise

    app.state.settings = settings
    app.state.store = store
    app.state.recent_ids = RecentReadingIds()

    tasks = [asyncio.create_task(demo_loop(app), name="demo-loop")]
    if settings.sensor_source == "hardware":
        tasks.append(asyncio.create_task(hardware_loop(app), name="hardware-loop"))
    if settings.change_stream_active:
        tasks.append(asyncio.create_task(change_stream_loop(app), name="change-stream"))

    logger.info(
        "AERO-HUB started | mode=%s storage=%s sensors=%s change_stream=%s",
        settings.data_mode,
        settings.storage_backend,
        settings.sensor_source,
        settings.change_stream_active,
    )

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        await store.close()
        logger.info("AERO-HUB stopped.")


app = FastAPI(title="AERO-HUB API", version="2.0.0", lifespan=lifespan)

allow_all_origins = "*" in settings.frontend_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all_origins else list(settings.frontend_origins),
    allow_credentials=not allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


if PyMongoError is not None:

    @app.exception_handler(PyMongoError)
    async def database_unavailable(request: Request, exc: PyMongoError):
        """Return a readable 503 instead of a 500 traceback when Atlas is down.

        The most common causes of a handshake failure are a public IP that is
        missing from the Atlas Network Access list and a paused free cluster.
        """
        logger.warning("Database unavailable for %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Database unavailable. Check MONGODB_URI and that this machine's "
                    "public IP is in the Atlas Network Access list "
                    "(run python -m app.check_mongo for details)."
                ),
                "error": type(exc).__name__,
            },
        )


@app.get("/health", include_in_schema=False)
async def health_alias():
    """Alias so simple uptime probes can hit /health instead of /api/health."""
    return await health_report(app.state.store, app.state.settings)


@app.websocket("/ws/readings")
async def readings_socket(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send the current reading immediately so a fresh dashboard is not blank.
        latest = await app.state.store.get_latest()
        if latest:
            await websocket.send_json({"type": "reading", "data": reading_payload(latest)})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        logger.exception("WebSocket connection failed.")
        manager.disconnect(websocket)
