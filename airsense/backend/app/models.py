from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, default=utc_now)
    temperature: Mapped[float | None] = mapped_column(Float)
    pressure: Mapped[float | None] = mapped_column(Float)
    altitude: Mapped[float | None] = mapped_column(Float)
    co_ppm: Mapped[float | None] = mapped_column(Float)
    mq135_raw: Mapped[float | None] = mapped_column(Float)
    mq135_estimated_ppm: Mapped[float | None] = mapped_column(Float)
    dust_voltage: Mapped[float | None] = mapped_column(Float)
    dust_ug_m3: Mapped[float | None] = mapped_column(Float)
    dust_particle_size: Mapped[str | None] = mapped_column(String(12))
    location_name: Mapped[str | None] = mapped_column(String(120), index=True)
    latitude: Mapped[float | None] = mapped_column(Float, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, index=True)
    source: Mapped[str] = mapped_column(String(32), default="raspberry_pi", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    alerts: Mapped[list["PollutionAlert"]] = relationship(back_populates="reading")


class SensorStatus(Base):
    __tablename__ = "sensor_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sensor_name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="offline")
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calibration_status: Mapped[str] = mapped_column(String(80), default="not calibrated")


class PollutionAlert(Base):
    __tablename__ = "pollution_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    alert_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(24), index=True)
    message: Mapped[str] = mapped_column(String(300))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    sensor_value: Mapped[float] = mapped_column(Float)
    reading_id: Mapped[int | None] = mapped_column(ForeignKey("sensor_readings.id"))
    reading: Mapped[SensorReading | None] = relationship(back_populates="alerts")


class SensorThreshold(Base):
    __tablename__ = "sensor_thresholds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sensor_name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    warning_threshold: Mapped[float] = mapped_column(Float)
    critical_threshold: Mapped[float] = mapped_column(Float)


class AppSetting(Base):
    __tablename__ = "app_settings"

    setting_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(1000))
