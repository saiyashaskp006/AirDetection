"""Raspberry Pi sensor access for direct mode.

This module is imported only when ``SENSOR_SOURCE=hardware``. On a normal
development machine the hardware packages are not required.
"""

from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime, timezone

from app.config import Settings

logger = logging.getLogger("aerohub.hardware")


def _env_float(name: str, default: float | None = None) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class HardwareReader:
    """Owns the SPI bus, dust LED GPIO and BMP280 handle."""

    def __init__(self, settings: Settings) -> None:
        import spidev
        from gpiozero import DigitalOutputDevice

        self.settings = settings
        self.vref = _env_float("ADC_VREF", 3.3) or 3.3
        self.load_resistor_kohm = _env_float("MQ_LOAD_RESISTOR_KOHM", 10.0) or 10.0
        self.mq7_channel = int(os.getenv("MQ7_ADC_CHANNEL", "0"))
        self.mq135_channel = int(os.getenv("MQ135_ADC_CHANNEL", "1"))
        self.dust_channel = int(os.getenv("DUST_ADC_CHANNEL", "2"))

        self.spi = spidev.SpiDev()
        self.spi.open(int(os.getenv("SPI_BUS", "0")), int(os.getenv("SPI_DEVICE", "0")))
        self.spi.max_speed_hz = int(os.getenv("SPI_SPEED_HZ", "1350000"))
        self.dust_led = DigitalOutputDevice(
            int(os.getenv("DUST_LED_GPIO", "17")),
            active_high=False,
            initial_value=False,
        )

        self.bmp = None
        try:
            import Adafruit_BMP.BMP280 as BMP280

            self.bmp = BMP280.BMP280()
        except Exception as exc:  # module missing or I2C not enabled
            logger.warning("BMP280 is unavailable; temperature/pressure will be omitted: %s", exc)

    def close(self) -> None:
        try:
            self.dust_led.close()
        finally:
            self.spi.close()

    def _analog_voltage(self, channel: int) -> float:
        if not 0 <= channel <= 7:
            raise ValueError(f"MCP3008 channel must be 0..7, got {channel}")
        response = self.spi.xfer2([1, (8 + channel) << 4, 0])
        value = ((response[1] & 3) << 8) + response[2]
        return value * self.vref / 1023

    def _gas_ppm(self, voltage: float, prefix: str) -> float | None:
        r0 = _env_float(f"{prefix}_R0_KOHM")
        slope = _env_float(f"{prefix}_CURVE_SLOPE")
        intercept = _env_float(f"{prefix}_CURVE_INTERCEPT")
        if voltage <= 0 or not r0 or not slope or intercept is None or r0 <= 0:
            return None
        resistance = self.load_resistor_kohm * (self.vref / voltage - 1)
        if resistance <= 0:
            return None
        log_ppm = (math.log10(resistance / r0) - intercept) / slope
        return round(10**log_ppm, 2)

    def _read_bmp280(self) -> dict:
        if self.bmp is None:
            return {}
        try:
            return {
                "temperature": round(self.bmp.read_temperature(), 2),
                "pressure": round(self.bmp.read_pressure() / 100, 2),
                "altitude": round(self.bmp.read_altitude(), 2),
            }
        except Exception as exc:
            logger.error("BMP280 read failed: %s", exc)
            return {}

    def _read_dust_voltage(self) -> float | None:
        try:
            self.dust_led.on()
            time.sleep(0.00028)
            voltage = self._analog_voltage(self.dust_channel)
            time.sleep(0.00004)
            self.dust_led.off()
            time.sleep(0.00968)
            return round(voltage, 3)
        except Exception as exc:
            self.dust_led.off()
            logger.error("Dust sensor read failed: %s", exc)
            return None

    def _calibrated_dust(self, voltage: float | None) -> float | None:
        zero = _env_float("DUST_ZERO_VOLTAGE")
        scale = _env_float("DUST_UG_M3_PER_V")
        if voltage is None or zero is None or scale is None:
            return None
        return round(max(0, (voltage - zero) * scale), 2)

    def read(self) -> dict:
        location = self.settings.device_location
        payload: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "raspberry_pi",
            "location_name": location.get("location_name"),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "dust_particle_size": self.settings.dust_particle_size,
        }
        payload.update(self._read_bmp280())

        try:
            mq7_voltage = self._analog_voltage(self.mq7_channel)
            mq135_voltage = self._analog_voltage(self.mq135_channel)
            payload["co_ppm"] = self._gas_ppm(mq7_voltage, "MQ7")
            payload["mq135_raw"] = round(mq135_voltage, 3)
            payload["mq135_estimated_ppm"] = self._gas_ppm(mq135_voltage, "MQ135")
        except Exception as exc:
            logger.error("Gas sensor ADC read failed: %s", exc)

        dust_voltage = self._read_dust_voltage()
        if dust_voltage is not None:
            payload["dust_voltage"] = dust_voltage
            payload["dust_ug_m3"] = self._calibrated_dust(dust_voltage)

        # Omit unavailable or uncalibrated values rather than uploading false zeroes.
        return {key: value for key, value in payload.items() if value is not None}
