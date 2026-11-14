"""Raspberry Pi sensor access for direct mode.

This module is imported only when ``SENSOR_SOURCE=hardware``. On a normal
development machine the hardware packages are not required.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.estimates import dust_ug_m3, gas_ppm

logger = logging.getLogger("aerohub.hardware")

_pi_modules: dict[str, object | None] = {}


def _load_pi_module(name: str):
    """Load a shared helper from ../raspberry_pi (peripherals, adc) if present.

    These helpers are local to the Pi, so a backend deployed without the
    repository simply runs without them.
    """
    if name in _pi_modules:
        return _pi_modules[name]
    path = Path(__file__).resolve().parents[2] / "raspberry_pi" / f"{name}.py"
    if not path.is_file():
        _pi_modules[name] = None
        return None
    try:
        spec = importlib.util.spec_from_file_location(f"aerohub_pi_{name}", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _pi_modules[name] = module
        return module
    except Exception as exc:  # pragma: no cover - depends on deployment layout
        logger.warning("Shared Pi module %s unavailable: %s", name, exc)
        _pi_modules[name] = None
        return None


def _env_float(name: str, default: float | None = None) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw, 0)
    except ValueError:
        return default


class HardwareReader:
    """Owns the ADC, dust LED GPIO, BMP280, optional GPS and LCD."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.load_resistor_kohm = _env_float("MQ_LOAD_RESISTOR_KOHM", 10.0) or 10.0
        # MQ sensors are heated from 5 V; their AOUT can reach 5 V, which exceeds
        # what a 3.3 V ADC can accept. A resistor divider may be fitted, so keep
        # the supply voltage and the divider ratio separate from the ADC reference.
        self.supply_voltage = _env_float("MQ_SUPPLY_VOLTAGE", 5.0) or 5.0
        legacy_divider = _env_float("ADC_DIVIDER_RATIO", 1.0) or 1.0
        self.mq_divider = max(1.0, _env_float("MQ_DIVIDER_RATIO", legacy_divider) or 1.0)
        self.dust_divider = max(1.0, _env_float("DUST_DIVIDER_RATIO", legacy_divider) or 1.0)
        self.mq7_channel = int(os.getenv("MQ7_ADC_CHANNEL", "0"))
        self.mq135_channel = int(os.getenv("MQ135_ADC_CHANNEL", "1"))
        self.dust_channel = int(os.getenv("DUST_ADC_CHANNEL", "2"))

        adc_backend = _load_pi_module("adc")
        if adc_backend is None:
            raise RuntimeError(
                "raspberry_pi/adc.py was not found next to the backend; run the "
                "backend from the repository or install the hardware packages."
            )
        self.adc = adc_backend.create_adc()

        self.dust_led = None
        self._dust_low_warned = False
        if self.adc is not None and not getattr(self.adc, "supports_dust", False):
            try:
                from gpiozero import DigitalOutputDevice
            except ImportError as exc:
                self.adc.close()
                raise RuntimeError(
                    "gpiozero is required to pulse the dust LED from the Pi; "
                    "set ARDUINO_DUST_LED=true to let an Arduino do it instead."
                ) from exc
            self.dust_led = DigitalOutputDevice(
                int(os.getenv("DUST_LED_GPIO", "17")),
                active_high=_env_bool("DUST_LED_ACTIVE_HIGH", False),
                initial_value=False,
            )

        self.bmp = None
        self.bmp_kind = None
        address = _env_int("BMP280_I2C_ADDRESS", 0x77)
        try:
            import adafruit_bmp280
            import board

            self.bmp = adafruit_bmp280.Adafruit_BMP280_I2C(board.I2C(), address=address)
            self.bmp_kind = "circuitpython"
            logger.info("BMP280 ready at I2C 0x%02X (circuitpython driver)", address)
        except ImportError:
            try:
                import Adafruit_BMP.BMP280 as BMP280

                self.bmp = BMP280.BMP280(address=address)
                self.bmp_kind = "legacy"
                logger.info("BMP280 ready at I2C 0x%02X (legacy driver)", address)
            except Exception as exc:  # module missing or I2C not enabled
                logger.warning(
                    "BMP280 is unavailable; temperature/pressure will be omitted: %s", exc
                )
        except Exception as exc:
            logger.warning("BMP280 init failed at I2C 0x%02X: %s", address, exc)

        self.peripherals = _load_pi_module("peripherals")
        self.gps = None
        self.lcd = None
        if self.peripherals is not None:
            self.gps = self.peripherals.create_gps()
            self.lcd = self.peripherals.create_lcd()

    def close(self) -> None:
        if self.gps is not None:
            self.gps.stop()
        if self.lcd is not None:
            self.lcd.close()
        if self.dust_led is not None:
            self.dust_led.close()
        if self.adc is not None:
            self.adc.close()

    def _analog_voltage(self, channel: int) -> float:
        if self.adc is None:
            raise RuntimeError("ADC is disabled (ADC_BACKEND=none)")
        return self.adc.voltage(channel)

    def _sensor_voltage(self, channel: int, ratio: float | None = None) -> float:
        """Voltage at the sensor output, undoing an external divider."""
        return self._analog_voltage(channel) * (ratio or self.mq_divider)

    def _gas_ppm(self, voltage: float, prefix: str) -> float | None:
        return gas_ppm(
            voltage,
            prefix,
            supply_voltage=self.supply_voltage,
            load_resistor_kohm=self.load_resistor_kohm,
        )

    def _read_bmp280(self) -> dict:
        if self.bmp is None:
            return {}
        try:
            if self.bmp_kind == "circuitpython":
                return {
                    "temperature": round(self.bmp.temperature, 2),
                    "pressure": round(self.bmp.pressure, 2),
                }
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
            if self.adc is not None and getattr(self.adc, "supports_dust", False):
                return round(self.adc.dust_voltage(), 3)
            if self.dust_led is None:
                return None
            self.dust_led.on()
            time.sleep(0.00028)
            voltage = self._sensor_voltage(self.dust_channel, self.dust_divider)
            time.sleep(0.00004)
            self.dust_led.off()
            time.sleep(0.00968)
            return round(voltage, 3)
        except Exception as exc:
            if self.dust_led is not None:
                with suppress(Exception):
                    self.dust_led.off()
            logger.error("Dust sensor read failed: %s", exc)
            return None

    def _calibrated_dust(self, voltage: float | None) -> float | None:
        # GP2Y1010AU0F datasheet: ~0.9 V at zero dust, ~0.005 V per ug/m3
        # (200 ug/m3 per volt). Users can override these with a reference
        # meter. A non-zero output below 0.9 V is clamped to zero.
        return dust_ug_m3(voltage)

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

        if self.adc is not None:
            try:
                mq7_voltage = self._sensor_voltage(self.mq7_channel)
                mq135_voltage = self._analog_voltage(self.mq135_channel)
                payload["co_ppm"] = self._gas_ppm(mq7_voltage, "MQ7")
                payload["mq135_raw"] = round(mq135_voltage, 3)
                payload["mq135_estimated_ppm"] = self._gas_ppm(
                    mq135_voltage * self.mq_divider, "MQ135"
                )
            except Exception as exc:
                logger.error("Gas sensor ADC read failed: %s", exc)

        dust_voltage = self._read_dust_voltage()
        if dust_voltage is not None:
            if dust_voltage < 0.5 and not self._dust_low_warned:
                self._dust_low_warned = True
                logger.warning(
                    "Dust output is %.3f V; a working GP2Y1010AU0F should be about "
                    "0.9 V with the LED on. Check the D7 transistor/LED polarity "
                    "(ARDUINO_DUST_LED_ACTIVE_HIGH), the 150 ohm LED resistor and "
                    "common ground.",
                    dust_voltage,
                )
            payload["dust_voltage"] = dust_voltage
            payload["dust_ug_m3"] = self._calibrated_dust(dust_voltage)

        fix = None
        if self.gps is not None:
            fix = self.gps.snapshot()
            if fix is not None and self.peripherals is not None:
                self.peripherals.apply_gps(payload, fix)

        # Omit unavailable or uncalibrated values rather than uploading false zeroes.
        result = {key: value for key, value in payload.items() if value is not None}

        if self.lcd is not None:
            try:
                self.lcd.show(result, fix, self.gps.status() if self.gps is not None else None)
            except Exception as exc:
                logger.warning("LCD update failed: %s", exc)
        return result
