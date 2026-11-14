"""Analog input backends for the Raspberry Pi.

The Pi has no analog inputs, so one of these is required:

* ``Mcp3008`` - 10-bit, 8 channels, SPI (the original design).
* ``Ads1x15`` - ADS1115 (16-bit) or ADS1015 (12-bit), 4 channels, I2C.
  Talks to the chip directly over ``smbus2``, so no Blinka/Adafruit stack
  is needed.

Select with ``ADC_BACKEND=mcp3008|ads1115|ads1015|arduino|none``.

The ``arduino`` backend uses an Arduino Uno (or any board running
``arduino/air_sensors/air_sensors.ino``) as the ADC. It converts the analog
inputs and sends the raw counts to the Pi over USB serial.
"""

from __future__ import annotations

import logging
import os
import time
from typing import ClassVar

logger = logging.getLogger("airsense.adc")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw, 0)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class AnalogSource:
    """Common interface: ``voltage(channel)`` returns volts at the pin."""

    label = "none"
    channels = 0
    # True when the backend can drive the dust LED and take the timed sample.
    supports_dust = False

    def voltage(self, channel: int) -> float:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        return None


class Mcp3008(AnalogSource):
    """10-bit SPI ADC, 8 single-ended channels, 0 .. ADC_VREF."""

    label = "mcp3008"
    channels = 8

    def __init__(
        self,
        bus: int = 0,
        device: int = 0,
        speed_hz: int = 1_350_000,
        vref: float = 3.3,
    ) -> None:
        import spidev

        self.vref = vref
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = speed_hz

    def voltage(self, channel: int) -> float:
        if not 0 <= channel < self.channels:
            raise ValueError(f"{self.label} channel must be 0..7, got {channel}")
        response = self.spi.xfer2([1, (8 + channel) << 4, 0])
        value = ((response[1] & 3) << 8) + response[2]
        return value * self.vref / 1023

    def close(self) -> None:
        self.spi.close()


class Ads1x15(AnalogSource):
    """Texas Instruments ADS1115 / ADS1015 over I2C (single-ended inputs).

    Power the module from **3.3 V**. Its I2C pull-ups then go to 3.3 V, which
    keeps the Pi's pins safe, and inputs above ~3.6 V must be divided down.
    """

    channels = 4

    # PGA setting -> full-scale range in volts.
    _PGA: ClassVar[dict[float, int]] = {
        6.144: 0b000,
        4.096: 0b001,
        2.048: 0b010,
        1.024: 0b011,
        0.512: 0b100,
        0.256: 0b101,
    }
    _RATES: ClassVar[dict[str, dict[int, int]]] = {
        "ads1115": {8: 0b000, 16: 0b001, 32: 0b010, 64: 0b011, 128: 0b100,
                    250: 0b101, 475: 0b110, 860: 0b111},
        "ads1015": {128: 0b000, 160: 0b001, 240: 0b010, 330: 0b011, 490: 0b100,
                    920: 0b101, 1600: 0b110, 3300: 0b111},
    }

    def __init__(
        self,
        chip: str = "ads1115",
        address: int = 0x48,
        bus: int = 1,
        full_scale: float = 4.096,
        data_rate: int = 860,
    ) -> None:
        try:
            import smbus2
        except ImportError as exc:  # pragma: no cover - depends on install
            raise RuntimeError(
                "The 'smbus2' package is required for ADS1015/ADS1115. "
                "Run: pip install smbus2"
            ) from exc

        if chip not in self._RATES:
            raise ValueError(f"Unsupported ADS chip: {chip!r}")
        if full_scale not in self._PGA:
            raise ValueError(
                f"ADS1X15_FULL_SCALE_V must be one of {sorted(self._PGA)}, got {full_scale}"
            )

        rates = self._RATES[chip]
        if data_rate not in rates:
            nearest = min(rates, key=lambda rate: abs(rate - data_rate))
            logger.warning("Data rate %s not supported, using %s SPS", data_rate, nearest)
            data_rate = nearest

        self.label = chip
        self.chip = chip
        self.address = address
        self.data_rate = data_rate
        self.full_scale = full_scale
        self.lsb = full_scale / 32768.0  # both chips return a left-justified value
        self._pga_code = self._PGA[full_scale]
        self._dr_code = rates[data_rate]
        self.bus = smbus2.SMBus(bus)

    def _config(self, channel: int) -> int:
        # OS=1 (start), single-ended MUX, PGA, single-shot, data rate,
        # comparator disabled (COMP_QUE=11).
        config = 0
        config |= 1 << 15
        config |= (0b100 + channel) << 12
        config |= self._pga_code << 9
        config |= 1 << 8
        config |= self._dr_code << 5
        config |= 0b11
        return config

    def voltage(self, channel: int) -> float:
        if not 0 <= channel < self.channels:
            raise ValueError(f"{self.label} channel must be 0..3, got {channel}")
        config = self._config(channel)
        self.bus.write_i2c_block_data(self.address, 0x01, [config >> 8, config & 0xFF])
        # One conversion takes 1/data_rate; wait a little longer, then read.
        time.sleep(max(0.0015, 1.25 / self.data_rate))
        raw = self.bus.read_i2c_block_data(self.address, 0x00, 2)
        value = (raw[0] << 8) | raw[1]
        if value & 0x8000:  # sign-extend to 16 bits
            value -= 0x10000
        return value * self.lsb

    def close(self) -> None:
        try:
            self.bus.close()
        except OSError:  # pragma: no cover - hardware specific
            pass


class SerialAdc(AnalogSource):
    """Arduino Uno as a 10-bit ADC over USB serial.

    The sketch in ``arduino/air_sensors/`` answers newline-terminated commands:

    * ``I``    -> ``AEROHUB,1``  (firmware identity, used as a handshake)
    * ``R<n>`` -> ``V,<raw>``    (``analogRead`` on A<n>)
    * ``D``    -> ``D,<raw>``    (pulse the dust LED and sample it)
    * ``L0/L1`` -> ``L,0/L,1``  (set dust LED active-low / active-high)

    ``MQ7_ADC_CHANNEL``, ``MQ135_ADC_CHANNEL`` and ``DUST_ADC_CHANNEL`` select
    the Arduino pin (A0 = 0 ... A5 = 5). The Uno's ADC is 5 V tolerant, so the
    MQ outputs can connect directly when this backend is used. The dust LED
    polarity is sent to the sketch at startup from
    ``ARDUINO_DUST_LED_ACTIVE_HIGH``; the sketch must include the L command.

    ``ARDUINO_PORT`` is ``/dev/ttyACM0`` (USB, official Uno), ``/dev/ttyUSB0``
    (CH340 clone), or ``/dev/serial0`` for the Pi's GPIO UART when the Uno has
    its own power supply. A GPIO UART does not reset the board, so
    ``ARDUINO_BOOT_SECONDS`` can be 0 in that case.
    """

    label = "arduino"
    channels = 6

    def __init__(
        self,
        port: str = "/dev/ttyACM0",
        baud: int = 115200,
        vref: float = 5.0,
        adc_max: int = 1023,
        timeout: float = 0.5,
        boot_seconds: float = 2.0,
        dust_led: bool = True,
        dust_led_active_high: bool = True,
    ) -> None:
        try:
            import serial
        except ImportError as exc:  # pragma: no cover - depends on install
            raise RuntimeError(
                "The 'pyserial' package is required for ADC_BACKEND=arduino. "
                "Run: pip install pyserial"
            ) from exc

        self.port = port
        self.vref = vref
        self.adc_max = adc_max
        self.supports_dust = dust_led
        self.dust_led_active_high = dust_led_active_high
        try:
            self._serial = serial.Serial(port, baud, timeout=timeout)
        except serial.SerialException as exc:
            raise RuntimeError(
                f"Cannot open {port}: {exc}. Check the USB cable, the port name "
                "(/dev/ttyACM0 for an official Uno, /dev/ttyUSB0 for CH340 "
                "clones) and that your user is in the 'dialout' group."
            ) from exc
        # Opening the port asserts DTR, which resets most Uno boards.
        time.sleep(max(0.0, boot_seconds))
        self._serial.reset_input_buffer()
        try:
            self._handshake()
            if self.supports_dust:
                self._set_dust_led_polarity()
        except Exception:
            # Do not leave the port open if the sketch is missing or the board
            # is not answering; the caller may retry initialization.
            try:
                self._serial.close()
            except OSError:
                pass
            raise

    def _handshake(self) -> None:
        for _ in range(5):
            if self._query("I").startswith("AEROHUB"):
                logger.info("ADC ready: Arduino on %s", self.port)
                return
            time.sleep(0.4)
        raise RuntimeError(
            f"No AERO-HUB reply on {self.port}. Check that the sketch is flashed, "
            "that the port is /dev/ttyACM0 (official Uno) or /dev/ttyUSB0 (CH340 "
            "clone), and that your user is in the 'dialout' group."
        )

    def _set_dust_led_polarity(self) -> None:
        """Tell the sketch whether the dust LED driver is active-high or low.

        Older sketches answer ``ERR,command`` and keep their compile-time
        setting; this is harmless. Reflash arduino/air_sensors/air_sensors.ino
        to use ARDUINO_DUST_LED_ACTIVE_HIGH from the environment.
        """
        self._serial.reset_input_buffer()
        self._serial.write(f"L{1 if self.dust_led_active_high else 0}\n".encode("ascii"))
        try:
            self._serial.readline()
        except (OSError, RuntimeError):
            pass

    def _query(self, command: str) -> str:
        self._serial.reset_input_buffer()
        self._serial.write(f"{command}\n".encode("ascii"))
        return self._serial.readline().decode("ascii", "replace").strip()

    def _read_raw(self, command: str) -> int:
        reply = ""
        for _ in range(2):
            reply = self._query(command)
            parts = reply.split(",")
            if len(parts) == 2:
                try:
                    return int(parts[1])
                except ValueError:
                    pass
        raise RuntimeError(
            f"Arduino did not answer {command!r} with a value (last reply {reply!r})"
        )

    def voltage(self, channel: int) -> float:
        if not 0 <= channel < self.channels:
            raise ValueError(f"{self.label} channel must be 0..5, got {channel}")
        return self._read_raw(f"R{channel}") * self.vref / self.adc_max

    def dust_voltage(self) -> float:
        return self._read_raw("D") * self.vref / self.adc_max

    def close(self) -> None:
        try:
            self._serial.close()
        except OSError:  # pragma: no cover - hardware specific
            pass


def create_adc() -> AnalogSource | None:
    """Build the configured ADC, or ``None`` when ``ADC_BACKEND=none``."""
    backend = (os.getenv("ADC_BACKEND") or "mcp3008").strip().lower()

    if backend in {"none", "off", "disabled"}:
        logger.info("ADC disabled (ADC_BACKEND=%s)", backend)
        return None

    if backend == "mcp3008":
        adc = Mcp3008(
            bus=_env_int("SPI_BUS", 0),
            device=_env_int("SPI_DEVICE", 0),
            speed_hz=_env_int("SPI_SPEED_HZ", 1_350_000),
            vref=_env_float("ADC_VREF", 3.3),
        )
        logger.info("ADC ready: MCP3008 over SPI0 CE%d", _env_int("SPI_DEVICE", 0))
        return adc

    if backend in {"ads1115", "ads1015"}:
        address = _env_int("ADS1X15_ADDRESS", _env_int("ADS1115_ADDRESS", 0x48))
        default_rate = 860 if backend == "ads1115" else 1600
        adc = Ads1x15(
            chip=backend,
            address=address,
            bus=_env_int("ADS1X15_I2C_BUS", _env_int("LCD_I2C_BUS", 1)),
            full_scale=_env_float("ADS1X15_FULL_SCALE_V", 4.096),
            data_rate=_env_int("ADS1X15_DATA_RATE", default_rate),
        )
        if _env_float("MQ_DIVIDER_RATIO", _env_float("ADC_DIVIDER_RATIO", 1.0)) <= 1.0:
            logger.warning(
                "MQ_DIVIDER_RATIO=1: a 5 V MQ output can exceed the %s input "
                "limit (3.3 V supply + 0.3 V) and damage it. Fit the 10k/20k "
                "divider and set MQ_DIVIDER_RATIO=1.5, or verify the output "
                "stays below 3.3 V.",
                backend.upper(),
            )
        logger.info("ADC ready: %s at I2C 0x%02X", backend.upper(), address)
        return adc

    if backend in {"arduino", "serial", "uno"}:
        return SerialAdc(
            port=(os.getenv("ARDUINO_PORT") or "/dev/ttyACM0").strip(),
            baud=_env_int("ARDUINO_BAUD", 115200),
            vref=_env_float("ARDUINO_VREF", 5.0),
            adc_max=_env_int("ARDUINO_ADC_MAX", 1023),
            timeout=_env_float("ARDUINO_TIMEOUT", 0.5),
            boot_seconds=_env_float("ARDUINO_BOOT_SECONDS", 2.0),
            dust_led=_env_bool("ARDUINO_DUST_LED", True),
            dust_led_active_high=_env_bool("ARDUINO_DUST_LED_ACTIVE_HIGH", True),
        )

    raise ValueError(
        f"Unknown ADC_BACKEND={backend!r}; use mcp3008, ads1115, ads1015, "
        "arduino, or none"
    )
