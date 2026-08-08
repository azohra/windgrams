"""Derives windgram profiles — the JSON consumers store and render — from
model source hours. Ported constant-for-constant from the original
club TypeScript; the committed data/ produced by that code is the
parity oracle for this module.

Dict key order is deliberate: it matches the original serialisation so
republished files diff cleanly.
"""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

WINDGRAM_MODEL = "HRDPS continental 2.5 km"
WINDGRAM_PRESSURE_LEVELS = (925, 900, 875, 850, 800, 750, 700, 650, 600)

# Profiles carry only hours a pilot can fly, in the sites' local time.
_TIME_ZONE = ZoneInfo("America/Vancouver")
_DAY_START_HOUR = 7
_DAY_END_HOUR = 21
_MIN_HOURS_PER_DAY = 5

_DRY_ADIABATIC_LAPSE_C_PER_M = 0.0098
_SINK_RATE_MS = 1.0
_HOUR_MS = 60 * 60 * 1000
_KMH_PER_MS = 3.6


def derive_windgram_profile(source: dict, model: str = WINDGRAM_MODEL) -> dict:
    hours = [_derive_hour(hour, source["modelElevationM"]) for hour in source["hours"]]
    _smooth_series(hours, "cloudBaseM")
    _smooth_series(hours, "usableLiftTopM")

    return {
        "generatedAt": source["generatedAt"],
        "model": model,
        "modelElevationM": source["modelElevationM"],
        "referenceTime": source["referenceTime"],
        "siteAltitudeM": source["siteAltitudeM"],
        "siteId": source["siteId"],
        "siteName": source["siteName"],
        "hours": hours,
    }


def windgram_display_hours(
    hours: list[dict], min_hours_per_day: int = _MIN_HOURS_PER_DAY
) -> list[dict]:
    """Keeps the hours inside the pilots' day, unless that would empty the set."""
    by_date: dict[str, list[dict]] = {}
    for hour in hours:
        local = _local_time(hour["validAt"])
        if local.hour < _DAY_START_HOUR or local.hour > _DAY_END_HOUR:
            continue
        by_date.setdefault(local.date().isoformat(), []).append(hour)

    complete_days = [
        date_hours for date_hours in by_date.values() if len(date_hours) >= min_hours_per_day
    ]
    if complete_days:
        return [hour for date_hours in complete_days for hour in date_hours]
    return hours


def _derive_hour(source: dict, model_elevation_m: float) -> dict:
    levels = sorted(
        (
            level
            for level in source["levels"]
            if math.isfinite(level["heightM"]) and level["heightM"] > model_elevation_m + 20
        ),
        key=lambda level: level["heightM"],
    )
    display_levels = []
    for index, level in enumerate(levels):
        next_level = levels[index + 1] if index + 1 < len(levels) else None
        lapse = (
            (next_level["temperatureC"] - level["temperatureC"])
            / (next_level["heightM"] - level["heightM"])
            * 304.8
            if next_level
            else None
        )
        display_levels.append(
            {
                "cloud": level["dewPointDepressionC"] < 0.5,
                "dewPointDepressionC": level["dewPointDepressionC"],
                "heightM": level["heightM"],
                "lapseCPer1000Ft": lapse,
                "pressureHpa": level["pressureHpa"],
                "temperatureC": level["temperatureC"],
                "windDirectionDeg": _normalize_degrees(level["windDirectionDeg"]),
                "windSpeedKmh": max(0.0, level["windSpeedMs"] * _KMH_PER_MS),
            }
        )

    cloud_base_m = _clamp_altitude(
        model_elevation_m + max(0.0, source["dewPointDepressionC"]) * 121,
        model_elevation_m,
    )
    boundary_layer_depth_m = _boundary_layer_depth(
        source["temperatureC"], model_elevation_m, levels
    )
    thermal_velocity_ms = _thermal_velocity(
        source["temperatureC"],
        source["sensibleHeatFluxWm2"],
        source["latentHeatFluxWm2"],
        boundary_layer_depth_m,
        levels[0]["pressureHpa"] if levels else None,
    )
    usable_lift_top_m = _usable_lift_top(
        model_elevation_m,
        cloud_base_m,
        boundary_layer_depth_m,
        thermal_velocity_ms,
        levels,
    )

    return {
        "boundaryLayerTopM": (
            model_elevation_m + boundary_layer_depth_m if boundary_layer_depth_m > 0 else None
        ),
        "cloudBaseM": cloud_base_m,
        "cloudCoverPercent": _clamp(source["cloudCoverPercent"], 0.0, 100.0),
        "precipitationMm": max(0.0, source["precipitationMm"]),
        "pressureKpa": source["pressurePa"] / 1000,
        "surfaceTemperatureC": source["temperatureC"],
        "thermalVelocityMs": thermal_velocity_ms,
        "usableLiftTopM": usable_lift_top_m,
        "validAt": source["validAt"],
        "windDirectionDeg": _normalize_degrees(source["windDirectionDeg"]),
        "windSpeedKmh": max(0.0, source["windSpeedMs"] * _KMH_PER_MS),
        "levels": display_levels,
    }


def _boundary_layer_depth(
    surface_temperature_c: float, model_elevation_m: float, levels: list[dict]
) -> float:
    for index, level in enumerate(levels):
        altitude_agl_m = level["heightM"] - model_elevation_m
        lifted_parcel_temperature_c = (
            surface_temperature_c - altitude_agl_m * _DRY_ADIABATIC_LAPSE_C_PER_M
        )
        if lifted_parcel_temperature_c > level["temperatureC"]:
            continue

        if index == 0:
            return max(0.0, altitude_agl_m)
        previous = levels[index - 1]
        previous_agl_m = previous["heightM"] - model_elevation_m
        lapse = (level["temperatureC"] - previous["temperatureC"]) / (
            level["heightM"] - previous["heightM"]
        )
        denominator = _DRY_ADIABATIC_LAPSE_C_PER_M + lapse
        if abs(denominator) < 0.00001:
            return max(0.0, previous_agl_m)
        return max(
            0.0,
            (surface_temperature_c - previous["temperatureC"] + lapse * previous_agl_m)
            / denominator,
        )

    if levels:
        return max(0.0, levels[-1]["heightM"] - model_elevation_m)
    return 0.0


def _thermal_velocity(
    surface_temperature_c: float,
    sensible_heat_flux_wm2: float,
    latent_heat_flux_wm2: float,
    boundary_layer_depth_m: float,
    first_pressure_hpa: float | None,
) -> float:
    if boundary_layer_depth_m <= 0 or first_pressure_hpa is None:
        return 0.0
    surface_temperature_k = surface_temperature_c + 273.15
    virtual_heat_flux = (
        sensible_heat_flux_wm2 + 0.000245268 * surface_temperature_k * latent_heat_flux_wm2
    )
    if virtual_heat_flux <= 0:
        return 0.0

    potential_temperature_k = surface_temperature_k * (1015 / first_pressure_hpa) ** 0.28482
    return math.cbrt(
        (0.0075516 / potential_temperature_k) * virtual_heat_flux * boundary_layer_depth_m
    )


def _usable_lift_top(
    model_elevation_m: float,
    cloud_base_m: float,
    boundary_layer_depth_m: float,
    thermal_velocity_ms: float,
    levels: list[dict],
) -> float | None:
    # canadarasp's hcrit, ported constant-for-constant: the height where the
    # STRONGEST core still out-climbs the sink rate. The 4 is Lenschow &
    # Stephens' average-updraft coefficient (1.34) times ~3 for the core, per
    # canadarasp's own derivation — which is why this line can legitimately sit
    # above the boundary layer: cores overshoot the mixed-layer top before they
    # die. Keep parity with canadarasp; pilots compare the two.
    if boundary_layer_depth_m <= 0 or thermal_velocity_ms * 2.02 < _SINK_RATE_MS:
        return None

    previous_altitude_agl_m = boundary_layer_depth_m * 0.2
    previous_updraft_ms = thermal_velocity_ms * 1.97

    for level in levels:
        altitude_agl_m = level["heightM"] - model_elevation_m
        if altitude_agl_m < boundary_layer_depth_m * 0.25:
            continue
        if level["heightM"] >= cloud_base_m:
            return cloud_base_m

        normalized_height = altitude_agl_m / boundary_layer_depth_m
        updraft_ms = (
            thermal_velocity_ms
            * 4
            * math.cbrt(max(0.0, normalized_height))
            * (1 - 0.8 * normalized_height)
        )
        if updraft_ms <= _SINK_RATE_MS:
            fraction = _clamp(
                (_SINK_RATE_MS - previous_updraft_ms) / (updraft_ms - previous_updraft_ms),
                0.0,
                1.0,
            )
            return min(
                cloud_base_m,
                model_elevation_m
                + previous_altitude_agl_m
                + fraction * (altitude_agl_m - previous_altitude_agl_m),
            )
        previous_altitude_agl_m = altitude_agl_m
        previous_updraft_ms = updraft_ms

    return min(cloud_base_m, model_elevation_m + boundary_layer_depth_m)


def _smooth_series(hours: list[dict], key: str) -> None:
    original = [hour[key] for hour in hours]
    for index in range(1, len(hours) - 1):
        previous_time = _epoch_ms(hours[index - 1]["validAt"])
        current_time = _epoch_ms(hours[index]["validAt"])
        next_time = _epoch_ms(hours[index + 1]["validAt"])
        if current_time - previous_time != _HOUR_MS or next_time - current_time != _HOUR_MS:
            continue
        previous, current, following = original[index - 1], original[index], original[index + 1]
        if previous is None or current is None or following is None:
            continue
        hours[index][key] = (previous + 2 * current + following) / 4


def _clamp_altitude(value: float, minimum: float) -> float:
    return max(minimum, value) if math.isfinite(value) else minimum


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _normalize_degrees(degrees: float) -> float:
    return ((degrees % 360) + 360) % 360


def _local_time(valid_at: str) -> datetime:
    return datetime.fromisoformat(valid_at.replace("Z", "+00:00")).astimezone(_TIME_ZONE)


def _epoch_ms(valid_at: str) -> int:
    return int(datetime.fromisoformat(valid_at.replace("Z", "+00:00")).timestamp() * 1000)
