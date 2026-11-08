from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReadingCreate(BaseModel):
    timestamp: datetime | None = None
    temperature: float | None = Field(default=None, ge=-80, le=100)
    pressure: float | None = Field(default=None, ge=100, le=1200)
    altitude: float | None = Field(default=None, ge=-1000, le=15000)
    co_ppm: float | None = Field(default=None, ge=0, le=10000)
    mq135_raw: float | None = Field(default=None, ge=0, le=5)
    mq135_estimated_ppm: float | None = Field(default=None, ge=0, le=100000)
    dust_voltage: float | None = Field(default=None, ge=0, le=5)
    dust_ug_m3: float | None = Field(default=None, ge=0, le=100000)
    dust_particle_size: Literal["unknown", "pm2_5", "pm10"] | None = "unknown"
    location_name: str | None = Field(default=None, min_length=1, max_length=120)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    source: Literal["raspberry_pi", "manual", "simulation"] = "raspberry_pi"

    @model_validator(mode="after")
    def require_sensor_value(self):
        if not any(
            getattr(self, key) is not None
            for key in ("temperature", "pressure", "co_ppm", "mq135_raw", "dust_voltage", "dust_ug_m3")
        ):
            raise ValueError("At least one sensor measurement is required")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be supplied together")
        if self.latitude is not None and not self.location_name:
            raise ValueError("A location name is required when coordinates are set")
        if self.location_name is not None:
            self.location_name = self.location_name.strip()
            if not self.location_name:
                raise ValueError("Location name cannot be blank")
        if self.timestamp and self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)
        return self


class ReadingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    temperature: float | None
    pressure: float | None
    altitude: float | None
    co_ppm: float | None
    mq135_raw: float | None
    mq135_estimated_ppm: float | None
    dust_voltage: float | None
    dust_ug_m3: float | None
    dust_particle_size: str | None
    location_name: str | None
    latitude: float | None
    longitude: float | None
    source: str


class ThresholdUpdate(BaseModel):
    warning_threshold: float = Field(ge=0)
    critical_threshold: float = Field(gt=0)

    @model_validator(mode="after")
    def critical_above_warning(self):
        if self.critical_threshold <= self.warning_threshold:
            raise ValueError("Critical threshold must be greater than warning threshold")
        return self


class DemoSetting(BaseModel):
    enabled: bool


class DemoLocation(BaseModel):
    location_name: str | None = Field(default=None, min_length=1, max_length=120)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_coordinates(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be supplied together")
        if self.location_name is not None:
            self.location_name = self.location_name.strip()
            if not self.location_name:
                raise ValueError("Location name cannot be blank")
        if self.latitude is not None and not self.location_name:
            raise ValueError("A location name is required when coordinates are set")
        return self
