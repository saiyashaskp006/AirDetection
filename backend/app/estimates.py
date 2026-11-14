"""Pure gas/dust estimates shared by ingestion and history serialization.

The dashboard shows the raw voltage fields for diagnostics, but users should
not have to read them. If a stored reading was written before the estimate
fields existed, ``derived_estimates`` fills those fields on read without
changing the database.
"""

from __future__ import annotations

import math
import os

# Approximate datasheet fits used when no calibration is configured.
GAS_CALIBRATION_DEFAULTS: dict[str, tuple[float, float, float]] = {
    # MQ-7:   19.32 * (Rs/R0)^-0.64
    "MQ7": (10.0, -1.5625, 2.009386),
    # MQ-135: 116.602 * (Rs/R0)^-2.769
    "MQ135": (76.63, -0.361141, 0.746373),
}
DUST_ZERO_VOLTAGE_DEFAULT = 0.9
DUST_UG_M3_PER_V_DEFAULT = 200.0


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def gas_ppm(
    voltage: float | None,
    prefix: str,
    *,
    supply_voltage: float | None = None,
    load_resistor_kohm: float | None = None,
) -> float | None:
    """Estimate ppm from an MQ sensor's log-log curve.

    Environment calibration (``*_R0_KOHM``, ``*_CURVE_SLOPE``,
    ``*_CURVE_INTERCEPT``) takes precedence over the datasheet defaults.
    """
    if voltage is None or voltage <= 0:
        return None

    default_r0, default_slope, default_intercept = GAS_CALIBRATION_DEFAULTS[prefix]
    r0 = _env_float(f"{prefix}_R0_KOHM", default_r0)
    slope = _env_float(f"{prefix}_CURVE_SLOPE", default_slope)
    intercept = _env_float(f"{prefix}_CURVE_INTERCEPT", default_intercept)
    supply = supply_voltage if supply_voltage is not None else _env_float(
        "MQ_SUPPLY_VOLTAGE", 5.0
    )
    load = load_resistor_kohm if load_resistor_kohm is not None else _env_float(
        "MQ_LOAD_RESISTOR_KOHM", 10.0
    )
    if r0 <= 0 or slope == 0 or supply <= 0 or load <= 0:
        return None

    resistance = load * (supply / voltage - 1)
    if resistance <= 0:
        return None
    log_ppm = (math.log10(resistance / r0) - intercept) / slope
    ppm = 10**log_ppm
    if not math.isfinite(ppm) or ppm < 0:
        return None
    limit = 10000.0 if prefix == "MQ7" else 100000.0
    return round(min(ppm, limit), 2)


def dust_ug_m3(voltage: float | None) -> float | None:
    """Estimate ug/m3 from the Sharp GP2Y1010AU0F linear output."""
    if voltage is None:
        return None
    zero = _env_float("DUST_ZERO_VOLTAGE", DUST_ZERO_VOLTAGE_DEFAULT)
    scale = _env_float("DUST_UG_M3_PER_V", DUST_UG_M3_PER_V_DEFAULT)
    return round(max(0.0, (voltage - zero) * scale), 2)


def derived_estimates(reading: dict) -> dict:
    """Return a copy with missing ppm/dust estimates calculated from raw values."""
    result = dict(reading)
    if result.get("mq135_estimated_ppm") is None and result.get("mq135_raw") is not None:
        legacy_divider = _env_float("ADC_DIVIDER_RATIO", 1.0)
        divider = max(1.0, _env_float("MQ_DIVIDER_RATIO", legacy_divider))
        result["mq135_estimated_ppm"] = gas_ppm(
            float(result["mq135_raw"]) * divider,
            "MQ135",
        )
    if result.get("dust_ug_m3") is None and result.get("dust_voltage") is not None:
        result["dust_ug_m3"] = dust_ug_m3(float(result["dust_voltage"]))
    return result
