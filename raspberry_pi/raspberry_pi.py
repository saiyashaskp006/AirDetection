#!/usr/bin/env python3
"""Cloud mode (mode 2): read sensors and POST readings to the AERO-HUB API.

Sensors are sampled and uploaded once per second (``SAMPLE_INTERVAL_SECONDS``,
default 1 s). Every reading is sent immediately, so the dashboard updates in
real time. Each request is tiny; 1 Hz is far below the Atlas free-tier limits.

The API is the only component that talks to MongoDB Atlas. Keep the database
credentials on the backend server, not on the Raspberry Pi.

For direct mode (mode 1) run the FastAPI backend on the Pi instead; see the
README section "Mode 1 - Raspberry Pi direct".

Optional extras, both off unless enabled in .env:

* ``GPS_ENABLED=true`` - read NMEA from a phone GPS app over TCP or UDP.
* ``LCD_ENABLED=true`` - show readings on a 16x2 I2C LCD.
"""

import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import adc as adc_module
import peripherals
import requests
from dotenv import load_dotenv

# Load raspberry_pi/.env regardless of the shell's current directory.
load_dotenv(Path(__file__).resolve().with_name(".env"))
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("airsense")

API_URL = os.getenv("AEROSENSE_API_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("AEROSENSE_API_KEY", "").strip()
# One sample and one upload per second. This is tiny (a few hundred bytes per
# request) and keeps the dashboard live. Slow it down with SAMPLE_INTERVAL_SECONDS.
INTERVAL = max(
    0.2,
    float(os.getenv("SAMPLE_INTERVAL_SECONDS", os.getenv("READ_INTERVAL_SECONDS", "1"))),
)
MQ_SUPPLY_VOLTAGE = float(os.getenv("MQ_SUPPLY_VOLTAGE", "5"))
_LEGACY_DIVIDER = max(1.0, float(os.getenv("ADC_DIVIDER_RATIO", "1")))
MQ_DIVIDER_RATIO = max(1.0, float(os.getenv("MQ_DIVIDER_RATIO", _LEGACY_DIVIDER)))
DUST_DIVIDER_RATIO = max(1.0, float(os.getenv("DUST_DIVIDER_RATIO", _LEGACY_DIVIDER)))
LOAD_RESISTOR_KOHM = float(os.getenv("MQ_LOAD_RESISTOR_KOHM", "10"))
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

# Fallback datasheet fits when no reference calibration is supplied. These are
# estimates, not laboratory measurements; overwrite the matching *_R0_KOHM and
# *_CURVE_* variables after calibrating against a known gas concentration.
GAS_CALIBRATION_DEFAULTS = {
    "MQ7": (10.0, -1.5625, 2.009386),       # 19.32 * (Rs/R0)^-0.64
    "MQ135": (76.63, -0.361141, 0.746373),  # 116.602 * (Rs/R0)^-2.769
}
DUST_ZERO_VOLTAGE_DEFAULT = 0.9
DUST_UG_M3_PER_V_DEFAULT = 200.0
_dust_low_warned = False


def _env_float(name, default):
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def sensor_voltage(adc, channel, ratio=None):
    """Voltage at the sensor output, undoing an external resistor divider."""
    return adc.voltage(channel) * (ratio or MQ_DIVIDER_RATIO)


def gas_ppm(voltage, sensor_prefix):
    """Estimate ppm from the MQ sensor's log-log curve.

    A configured calibration (R0 + slope + intercept) takes precedence. When
    those values are blank, an approximate datasheet fit is used so the
    dashboard still shows a meaningful concentration.
    """
    default_r0, default_slope, default_intercept = GAS_CALIBRATION_DEFAULTS[sensor_prefix]
    r0 = _env_float(f"{sensor_prefix}_R0_KOHM", default_r0)
    slope = _env_float(f"{sensor_prefix}_CURVE_SLOPE", default_slope)
    intercept = _env_float(f"{sensor_prefix}_CURVE_INTERCEPT", default_intercept)
    if voltage <= 0 or r0 <= 0 or slope == 0:
        return None
    resistance = LOAD_RESISTOR_KOHM * (MQ_SUPPLY_VOLTAGE / voltage - 1)
    if resistance <= 0:
        return None
    log_ppm = (math.log10(resistance / r0) - intercept) / slope
    ppm = 10**log_ppm
    if not math.isfinite(ppm) or ppm < 0:
        return None
    limit = 10000.0 if sensor_prefix == "MQ7" else 100000.0
    return round(min(ppm, limit), 2)


def read_bmp280():
    """Read the BMP280/HW-611, trying the modern driver before the legacy one.

    HW-611 modules answer on 0x76 or 0x77 depending on the SDO pin, so the
    address is configurable with BMP280_I2C_ADDRESS.
    """
    global _bmp_sensor, _bmp_kind
    if _bmp_sensor is None:
        _bmp_sensor = _init_bmp280()
        if _bmp_sensor is None:
            return {}
    try:
        if _bmp_kind == "circuitpython":
            return {
                "temperature": round(_bmp_sensor.temperature, 2),
                "pressure": round(_bmp_sensor.pressure, 2),
            }
        return {
            "temperature": round(_bmp_sensor.read_temperature(), 2),
            "pressure": round(_bmp_sensor.read_pressure() / 100, 2),
            "altitude": round(_bmp_sensor.read_altitude(), 2),
        }
    except (OSError, RuntimeError, ValueError) as error:
        logger.error("BMP280 read failed: %s", error)
        _bmp_sensor = None
        return {}


_bmp_sensor = None
_bmp_kind = None


def _init_bmp280():
    global _bmp_kind
    raw = os.getenv("BMP280_I2C_ADDRESS", "").strip()
    address = int(raw, 0) if raw else 0x77
    try:
        import board
        import adafruit_bmp280

        sensor = adafruit_bmp280.Adafruit_BMP280_I2C(board.I2C(), address=address)
        _bmp_kind = "circuitpython"
        logger.info("BMP280 ready on I2C address 0x%02X (circuitpython driver)", address)
        return sensor
    except ImportError:
        pass
    except (OSError, ValueError) as error:
        logger.warning("Modern BMP280 driver failed at 0x%02X: %s", address, error)
    try:
        import Adafruit_BMP.BMP280 as BMP280

        sensor = BMP280.BMP280(address=address)
        _bmp_kind = "legacy"
        logger.info("BMP280 ready on I2C address 0x%02X (legacy driver)", address)
        return sensor
    except ImportError:
        logger.error(
            "No BMP280 library found. Install adafruit-circuitpython-bmp280 + "
            "adafruit-blinka, or Adafruit-BMP."
        )
    except (OSError, RuntimeError, ValueError) as error:
        logger.error("BMP280 not detected at 0x%02X: %s", address, error)
    return None


def read_dust_voltage(adc, led):
    """Sample the Sharp sensor during its LED pulse.

    With the Arduino backend the Uno drives the LED itself, which keeps the
    280 us sample timing precise even though the value travels over serial.
    """
    if adc is not None and getattr(adc, "supports_dust", False):
        try:
            return round(adc.dust_voltage(), 3)
        except (OSError, RuntimeError, ValueError) as error:
            logger.error("Dust sensor read failed: %s", error)
            return None
    if led is None:
        return None
    try:
        led.on()
        time.sleep(0.00028)
        voltage = sensor_voltage(adc, int(os.getenv("DUST_ADC_CHANNEL", "2")), DUST_DIVIDER_RATIO)
        time.sleep(0.00004)
        led.off()
        time.sleep(0.00968)
        return round(voltage, 3)
    except (OSError, RuntimeError, ValueError) as error:
        led.off()
        logger.error("Dust sensor read failed: %s", error)
        return None


def calibrated_dust_estimate(voltage):
    """Estimate ug/m3 from the Sharp sensor's linear output.

    The defaults match the GP2Y1010AU0F datasheet (~0.9 V at zero dust and
    ~0.005 V per ug/m3). DUST_ZERO_VOLTAGE and DUST_UG_M3_PER_V override them
    with values from a reference instrument. Invalid values fall back to the
    defaults so they can never stop a reading from being uploaded.
    """
    zero = _env_float("DUST_ZERO_VOLTAGE", DUST_ZERO_VOLTAGE_DEFAULT)
    scale = _env_float("DUST_UG_M3_PER_V", DUST_UG_M3_PER_V_DEFAULT)
    if voltage is None:
        return None
    return round(max(0.0, (voltage - zero) * scale), 2)


def read_sensors(adc, dust_led):
    global _dust_low_warned
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "raspberry_pi",
        "location_name": os.getenv("AEROSENSE_SITE_NAME") or None,
        "latitude": float(os.environ["AEROSENSE_LATITUDE"]) if os.getenv("AEROSENSE_LATITUDE") else None,
        "longitude": float(os.environ["AEROSENSE_LONGITUDE"]) if os.getenv("AEROSENSE_LONGITUDE") else None,
        "dust_particle_size": os.getenv("DUST_PARTICLE_SIZE", "unknown"),
    }
    payload.update(read_bmp280())
    if adc is not None:
        try:
            mq7_voltage = sensor_voltage(adc, int(os.getenv("MQ7_ADC_CHANNEL", "0")))
            mq135_voltage = adc.voltage(int(os.getenv("MQ135_ADC_CHANNEL", "1")))
            payload["co_ppm"] = gas_ppm(mq7_voltage, "MQ7")
            payload["mq135_raw"] = round(mq135_voltage, 3)
            payload["mq135_estimated_ppm"] = gas_ppm(mq135_voltage * MQ_DIVIDER_RATIO, "MQ135")
        except (OSError, RuntimeError, ValueError) as error:
            logger.error("Gas sensor ADC read failed: %s", error)

    dust_voltage = read_dust_voltage(adc, dust_led) if adc is not None else None
    if dust_voltage is not None:
        if dust_voltage < 0.5 and not _dust_low_warned:
            _dust_low_warned = True
            logger.warning(
                "Dust output is %.3f V; a working GP2Y1010AU0F should be about "
                "0.9 V with the LED on. Check the D7 transistor/LED polarity "
                "(ARDUINO_DUST_LED_ACTIVE_HIGH), the 150 ohm LED resistor and "
                "common ground.",
                dust_voltage,
            )
        payload["dust_voltage"] = dust_voltage
        payload["dust_ug_m3"] = calibrated_dust_estimate(dust_voltage)
    # Omit unavailable or uncalibrated values rather than uploading false zeroes.
    return {key: value for key, value in payload.items() if value is not None}


def send_reading(payload, session):
    delay = 1
    for attempt in range(5):
        try:
            response = session.post(
                f"{API_URL}/api/sensors/readings",
                json=payload,
                headers=HEADERS,
                timeout=5,
            )
            response.raise_for_status()
            logger.debug("Reading sent (HTTP %s)", response.status_code)
            return True
        except requests.RequestException as error:
            if attempt == 4:
                logger.error("Could not send reading after 5 attempts: %s", error)
                return False
            logger.warning("Send failed; retrying in %s seconds: %s", delay, error)
            time.sleep(delay)
            delay = min(delay * 2, 8)
    return False


def has_measurement(payload):
    return any(
        payload.get(key) is not None
        for key in (
            "temperature",
            "pressure",
            "co_ppm",
            "mq135_raw",
            "mq135_estimated_ppm",
            "dust_voltage",
            "dust_ug_m3",
        )
    )


def main():
    try:
        adc = adc_module.create_adc()
    except (ImportError, RuntimeError, ValueError) as error:
        raise SystemExit(f"ADC setup failed: {error}") from error

    dust_led = None
    if adc is not None and not getattr(adc, "supports_dust", False):
        try:
            from gpiozero import DigitalOutputDevice
        except ImportError as error:
            adc.close()
            raise SystemExit(
                "Install the Raspberry Pi packages in raspberry_pi/requirements.txt "
                "(gpiozero), or set ARDUINO_DUST_LED=true so the Arduino pulses "
                "the dust LED."
            ) from error
        dust_led = DigitalOutputDevice(
            int(os.getenv("DUST_LED_GPIO", "17")),
            active_high=os.getenv("DUST_LED_ACTIVE_HIGH", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            initial_value=False,
        )
    session = requests.Session()
    gps = peripherals.create_gps()
    lcd = peripherals.create_lcd()
    logger.info(
        "AERO-HUB sensor client sending to %s every %ss (device key %s, gps %s, lcd %s)",
        API_URL,
        INTERVAL,
        "configured" if API_KEY else "disabled",
        "on" if gps else "off",
        "on" if lcd else "off",
    )
    try:
        uploaded = 0
        while True:
            started = time.monotonic()
            try:
                payload = read_sensors(adc, dust_led)
                fix = gps.snapshot() if gps else None
                if fix:
                    peripherals.apply_gps(payload, fix)
                if has_measurement(payload):
                    if send_reading(payload, session):
                        uploaded += 1
                        if uploaded % 60 == 0:
                            logger.info("Uploaded %s readings to %s", uploaded, API_URL)
                else:
                    logger.error("No sensor readings available; nothing was uploaded.")
                if lcd:
                    lcd.show(payload, fix, gps.status() if gps else None)
            except (OSError, RuntimeError, ValueError) as error:
                logger.exception("Sensor cycle failed: %s", error)
            time.sleep(max(0, INTERVAL - (time.monotonic() - started)))
    except KeyboardInterrupt:
        logger.info("Stopping sensor client.")
    finally:
        if gps:
            gps.stop()
        if lcd:
            lcd.close()
        if dust_led is not None:
            dust_led.close()
        if adc is not None:
            adc.close()
        session.close()


if __name__ == "__main__":
    main()
