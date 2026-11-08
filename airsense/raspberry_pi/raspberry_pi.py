#!/usr/bin/env python3
"""Read AeroSense sensors through MCP3008 and POST measurements to the API."""

import logging
import math
import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("airsense")

API_URL = os.getenv("AEROSENSE_API_URL", "http://localhost:8000").rstrip("/")
INTERVAL = max(1, float(os.getenv("READ_INTERVAL_SECONDS", "5")))
VREF = float(os.getenv("ADC_VREF", "3.3"))
LOAD_RESISTOR_KOHM = float(os.getenv("MQ_LOAD_RESISTOR_KOHM", "10"))


def analog_voltage(spi, channel):
    if not 0 <= channel <= 7:
        raise ValueError(f"MCP3008 channel must be 0..7, got {channel}")
    response = spi.xfer2([1, (8 + channel) << 4, 0])
    value = ((response[1] & 3) << 8) + response[2]
    return value * VREF / 1023


def gas_ppm(voltage, sensor_prefix):
    """Return a concentration only when the sensor curve has been calibrated."""
    r0 = os.getenv(f"{sensor_prefix}_R0_KOHM")
    slope = os.getenv(f"{sensor_prefix}_CURVE_SLOPE")
    intercept = os.getenv(f"{sensor_prefix}_CURVE_INTERCEPT")
    if voltage <= 0 or not r0 or not slope or not intercept:
        return None
    resistance = LOAD_RESISTOR_KOHM * (VREF / voltage - 1)
    if resistance <= 0 or float(r0) <= 0:
        return None
    log_ppm = (math.log10(resistance / float(r0)) - float(intercept)) / float(slope)
    return round(10**log_ppm, 2)


def read_bmp280():
    try:
        import Adafruit_BMP.BMP280 as BMP280

        sensor = BMP280.BMP280()
        temperature = round(sensor.read_temperature(), 2)
        pressure = round(sensor.read_pressure() / 100, 2)
        altitude = round(sensor.read_altitude(), 2)
        return {"temperature": temperature, "pressure": pressure, "altitude": altitude}
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        logger.error("BMP280 read failed: %s", error)
        return {}


def read_dust_voltage(spi, led):
    """Sample the Sharp sensor during its LED pulse; verify timing on your hardware."""
    if led is None:
        return None
    try:
        led.on()
        time.sleep(0.00028)
        voltage = analog_voltage(spi, int(os.getenv("DUST_ADC_CHANNEL", "2")))
        time.sleep(0.00004)
        led.off()
        time.sleep(0.00968)
        return round(voltage, 3)
    except (OSError, RuntimeError, ValueError) as error:
        led.off()
        logger.error("Dust sensor read failed: %s", error)
        return None


def calibrated_dust_estimate(voltage):
    """Optional linear calibration: estimate = (volts - zero) * configured scale."""
    zero = os.getenv("DUST_ZERO_VOLTAGE")
    scale = os.getenv("DUST_UG_M3_PER_V")
    if voltage is None or zero is None or scale is None:
        return None
    return round(max(0, (voltage - float(zero)) * float(scale)), 2)


def read_sensors(spi, dust_led):
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "raspberry_pi",
        "location_name": os.getenv("AEROSENSE_SITE_NAME") or None,
        "latitude": float(os.environ["AEROSENSE_LATITUDE"]) if os.getenv("AEROSENSE_LATITUDE") else None,
        "longitude": float(os.environ["AEROSENSE_LONGITUDE"]) if os.getenv("AEROSENSE_LONGITUDE") else None,
        "dust_particle_size": os.getenv("DUST_PARTICLE_SIZE", "unknown"),
    }
    payload.update(read_bmp280())
    try:
        mq7_voltage = analog_voltage(spi, int(os.getenv("MQ7_ADC_CHANNEL", "0")))
        mq135_voltage = analog_voltage(spi, int(os.getenv("MQ135_ADC_CHANNEL", "1")))
        payload["co_ppm"] = gas_ppm(mq7_voltage, "MQ7")
        payload["mq135_raw"] = round(mq135_voltage, 3)
        payload["mq135_estimated_ppm"] = gas_ppm(mq135_voltage, "MQ135")
    except (OSError, RuntimeError, ValueError) as error:
        logger.error("Gas sensor ADC read failed: %s", error)

    dust_voltage = read_dust_voltage(spi, dust_led)
    if dust_voltage is not None:
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
                timeout=5,
            )
            response.raise_for_status()
            logger.info("Reading sent (HTTP %s)", response.status_code)
            return True
        except requests.RequestException as error:
            if attempt == 4:
                logger.error("Could not send reading after 5 attempts: %s", error)
                return False
            logger.warning("Send failed; retrying in %s seconds: %s", delay, error)
            time.sleep(delay)
            delay = min(delay * 2, 8)
    return False


def main():
    try:
        import spidev
        from gpiozero import DigitalOutputDevice
    except ImportError as error:
        raise SystemExit(
            "Install the Raspberry Pi packages in README.md before running the sensor client."
        ) from error

    spi = spidev.SpiDev()
    spi.open(int(os.getenv("SPI_BUS", "0")), int(os.getenv("SPI_DEVICE", "0")))
    spi.max_speed_hz = 1_350_000
    dust_led = DigitalOutputDevice(
        int(os.getenv("DUST_LED_GPIO", "17")),
        active_high=False,
        initial_value=False,
    )
    session = requests.Session()
    logger.info("AeroSense sensor client sending to %s every %ss", API_URL, INTERVAL)
    try:
        while True:
            started = time.monotonic()
            try:
                payload = read_sensors(spi, dust_led)
                if len(payload) > 2:
                    send_reading(payload, session)
                else:
                    logger.error("No sensor readings available; nothing was uploaded.")
            except (OSError, RuntimeError, ValueError) as error:
                logger.exception("Sensor cycle failed: %s", error)
            time.sleep(max(0, INTERVAL - (time.monotonic() - started)))
    except KeyboardInterrupt:
        logger.info("Stopping sensor client.")
    finally:
        dust_led.close()
        spi.close()
        session.close()


if __name__ == "__main__":
    main()
