"""Shared constants used by the storage, API and alerting layers."""

DEFAULT_THRESHOLDS: dict[str, tuple[float, float]] = {
    "co": (9.0, 35.0),
    # MQ-135 is a broad-spectrum estimate, not a calibrated CO2 measurement.
    # These ppm defaults are for the project indicator only.
    "mq135": (1000.0, 2000.0),
    "dust": (35.0, 150.0),
}

# Older releases stored the MQ-135 threshold as raw volts. Migrate only that
# exact default so a user-customized voltage threshold is not overwritten.
LEGACY_MQ135_THRESHOLDS = (2.5, 4.0)

# Friendly sensor name -> fields that prove the sensor reported in a reading.
# Put the display field first: build_statuses() uses this order for the value
# shown on the sensor-management page.
SENSOR_PRESENCE: dict[str, tuple[str, ...]] = {
    "BMP280": ("temperature", "pressure"),
    "MQ-7": ("co_ppm",),
    "MQ-135": ("mq135_estimated_ppm", "mq135_raw"),
    "Sharp dust": ("dust_ug_m3", "dust_voltage"),
}

KNOWN_SENSORS = tuple(SENSOR_PRESENCE)

# Threshold key -> (reading field, human label, unit)
SENSOR_FIELDS: dict[str, tuple[str, str, str]] = {
    "co": ("co_ppm", "CO", "ppm"),
    "mq135": ("mq135_estimated_ppm", "MQ-135 estimate", "ppm"),
    "dust": ("dust_ug_m3", "Dust", "µg/m³"),
}

STATISTICS_FIELDS = (
    "temperature",
    "pressure",
    "co_ppm",
    "mq135_estimated_ppm",
    "mq135_raw",
    "dust_ug_m3",
)

WHO_DAILY_GUIDELINES = {"pm2_5": 15.0, "pm10": 45.0}
