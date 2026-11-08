import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import models
from app.database import Base, SessionLocal, engine
from app.routes import demo_location_settings, demo_mode_default, router
from app.services import get_persisted_setting, save_reading, simulated_reading
from app.websocket import manager

load_dotenv()
demo_interval = max(1, int(os.getenv("DEMO_INTERVAL_SECONDS", "5")))
logger = logging.getLogger("airsense")


async def demo_loop():
    while True:
        try:
            with SessionLocal() as db:
                demo_enabled = get_persisted_setting(db, "demo_enabled", demo_mode_default)
                if demo_enabled:
                    location = get_persisted_setting(db, "demo_location", demo_location_settings)
                    reading = save_reading(db, simulated_reading(location))
                    from app.services import reading_payload

                    await manager.broadcast({"type": "reading", "data": reading_payload(reading)})
        except SQLAlchemyError:
            logger.exception("Could not save or broadcast a simulated sensor reading.")
        await asyncio.sleep(demo_interval)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    task = asyncio.create_task(demo_loop())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="AERO-HUB API", version="1.0.0", lifespan=lifespan)
origins = [origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/api/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.websocket("/ws/readings")
async def readings_socket(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
