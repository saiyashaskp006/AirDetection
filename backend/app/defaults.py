"""Shared constants used by the storage, API and alerting layers."""

DEFAULT_THRESHOLDS: dict[str, tuple[float, float]] = {
    "co": (9.0, 35.0),
    "mq135": (2.5, 4.0),
    "dust": (35.0, 150.0),
}

# Friendly sensor name -> fields that prove the sensor reported in a reading.
SENSOR_PRESENCE: dict[str, tuple[str, ...]] = {
    "BMP280": ("temperature", "pressure"),
    "MQ-7": ("co_ppm",),
    "MQ-135": ("mq135_raw", "mq135_estimated_ppm"),
    "Sharp dust": ("dust_voltage", "dust_ug_m3"),
}

KNOWN_SENSORS = tuple(SENSOR_PRESENCE)

# Threshold key -> (reading field, human label, unit)
SENSOR_FIELDS: dict[str, tuple[str, str, str]] = {
    "co": ("co_ppm", "CO", "ppm"),
    "mq135": ("mq135_raw", "MQ-135", "V"),
    "dust": ("dust_ug_m3", "Dust", "µg/m³"),
}

STATISTICS_FIELDS = ("temperature", "pressure", "co_ppm", "mq135_raw", "dust_ug_m3")

WHO_DAILY_GUIDELINES = {"pm2_5": 15.0, "pm10": 45.0}
