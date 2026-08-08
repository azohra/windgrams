"""Builds windgram profiles from NOAA's HRRR CONUS 3 km model.

HRRR publishes whole-domain GRIB2 files with .idx sidecars on a public S3
bucket. Every record this build needs lives in the wrfprs file, so each
forecast hour costs one .idx fetch plus ~54 ranged record fetches. Only the
00/06/12/18Z cycles run to 48 h, and f48 publishes last, so a cycle whose
f48 index exists is complete.

HRRR winds are grid-relative on the model's Lambert conformal projection;
they are rotated to true north before speeds and FROM-directions are
derived. Set WINDGRAMS_MAX_STEPS to cap the forecast steps fetched (used by
smoke tests).
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .noaa import (
    DownloadStats,
    IdxRecord,
    exists,
    fetch_index,
    fetch_record,
    find_record,
    sample_sites,
    wind_from_uv,
)
from .publish import append_history, write_json
from .windgram import derive_windgram_profile, windgram_display_hours

MODEL = "HRRR CONUS 3 km"
BASE_URL = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"
OUT_DIR = Path("data/hrrr-conus")
RUN_HOURS = ("18", "12", "06", "00")  # Only the synoptic cycles run to 48 h.
FORECAST_HOURS = 48
FETCH_CONCURRENCY = 6
# On the 3 km grid the nearest gridpoint is within ~2 km; anything farther
# means ecCodes clamped an out-of-domain site to the grid boundary.
MAX_NEAREST_KM = 5.0

KELVIN = 273.15
# field → (GRIB variable, level, conversion). PRATE is an instantaneous rate
# (kg/m²/s); ×3600 approximates the other builds' quantity-per-hour
# precipitation. HRRR carries no PRMSL; MSLMA is its MAPS mean sea level
# pressure in Pa. 2 m temperature/dewpoint and the winds need pairs of
# records, so they are derived in their own tasks below.
SURFACE_FIELDS = {
    "cloudCoverPercent": ("TCDC", "entire atmosphere", lambda v: v),
    "latentHeatFluxWm2": ("LHTFL", "surface", lambda v: v),
    "precipitationMm": ("PRATE", "surface", lambda v: v * 3600),
    "pressurePa": ("MSLMA", "mean sea level", lambda v: v),
    "sensibleHeatFluxWm2": ("SHTFL", "surface", lambda v: v),
}
PRESSURE_LEVELS = (925, 900, 875, 850, 800, 750, 700, 650, 600)

# HRRR's Lambert conformal projection: Latin1 = Latin2 = LaD = 38.5°,
# LoV = 262.5°. With one standard parallel the cone constant is sin(LaD).
_LAMBERT_CONE = math.sin(math.radians(38.5))
_LAMBERT_ORIENTATION_DEG = 262.5


def main() -> None:
    sites = json.loads(Path("sites.json").read_text())
    if not sites:
        raise RuntimeError("sites.json is empty")

    run = _latest_complete_run()
    if run is None:
        print("No complete HRRR run is available.")
        return
    date = run["date"]
    reference_time = f"{date[:4]}-{date[4:6]}-{date[6:]}T{run['hour']}:00:00Z"
    if _published_reference_time() == reference_time:
        print(f"HRRR run {reference_time} is already published.")
        return

    print(f"Building HRRR {reference_time} for {len(sites)} sites…")
    started_at = time.monotonic()
    stats = DownloadStats()
    result = _build_profiles(run, reference_time, sites, stats)

    sites_dir = OUT_DIR / "sites"
    sites_dir.mkdir(parents=True, exist_ok=True)
    for profile in result["profiles"]:
        write_json(sites_dir / f"{profile['siteId']}.json", profile, compact=True)
        append_history(profile, OUT_DIR / "history")
    manifest = {
        "firstForecastHour": result["firstForecastHour"],
        "forecastHours": result["forecastHours"],
        "generatedAt": _instant(),
        "lastForecastHour": result["lastForecastHour"],
        "model": MODEL,
        "referenceTime": reference_time,
        "sites": [{"name": site["name"], "slug": site["slug"]} for site in sites],
        "stats": {
            "downloadBytes": stats.response_bytes,
            "downloads": stats.requests,
            "durationMs": round((time.monotonic() - started_at) * 1000),
            "retries": stats.retries,
        },
    }
    write_json(OUT_DIR / "manifest.json", manifest, compact=False)
    print(
        f"Published {len(result['profiles'])} HRRR profiles for {reference_time} "
        f"({stats.requests} requests, {stats.response_bytes // (1024 * 1024)} MiB)."
    )


def _latest_complete_run() -> dict | None:
    """A cycle is complete when its final forecast hour's index is on S3."""
    now = datetime.now(timezone.utc)
    for day_offset in (0, 1):
        date = (now - timedelta(days=day_offset)).strftime("%Y%m%d")
        for hour in RUN_HOURS:
            if day_offset == 0 and int(hour) > now.hour:
                continue
            if exists(_file_url(date, hour, FORECAST_HOURS) + ".idx"):
                return {"date": date, "hour": hour}
    return None


def _file_url(date: str, run_hour: str, forecast_hour: int) -> str:
    return f"{BASE_URL}/hrrr.{date}/conus/hrrr.t{run_hour}z.wrfprsf{forecast_hour:02d}.grib2"


def _published_reference_time() -> str | None:
    try:
        return json.loads((OUT_DIR / "manifest.json").read_text())["referenceTime"]
    except (OSError, KeyError, ValueError):
        return None


def _build_profiles(run: dict, reference_time: str, sites: list[dict], stats: DownloadStats):
    forecast_slots = windgram_display_hours(
        [
            {"forecastHour": hour, "validAt": _valid_time(reference_time, hour)}
            for hour in range(1, FORECAST_HOURS + 1)
        ]
    )
    forecast_slots = forecast_slots[: _max_steps()]
    first_forecast_hour = forecast_slots[0]["forecastHour"]

    records_by_hour: dict[int, list[IdxRecord]] = {}

    def index_task(forecast_hour: int):
        def run_task() -> None:
            url = _file_url(run["date"], run["hour"], forecast_hour) + ".idx"
            records_by_hour[forecast_hour] = fetch_index(url, stats)

        return run_task

    _run_concurrent([index_task(slot["forecastHour"]) for slot in forecast_slots])

    def record_values(forecast_hour: int, variable: str, level: str):
        record = find_record(
            records_by_hour[forecast_hour], variable, level, f"{forecast_hour} hour fcst"
        )
        data = fetch_record(_file_url(run["date"], run["hour"], forecast_hour), record, stats)
        return sample_sites(data, sites, MAX_NEAREST_KM)

    def wind_values(forecast_hour: int, level: str) -> dict[str, tuple[float, float] | None]:
        """Speed and true-north FROM direction per site, or None when the
        gridpoint is missing from either component."""
        u = record_values(forecast_hour, "UGRD", level)
        v = record_values(forecast_hour, "VGRD", level)
        winds: dict[str, tuple[float, float] | None] = {}
        for site in sites:
            slug = site["slug"]
            if u[slug].value is None or v[slug].value is None:
                winds[slug] = None
                continue
            u_earth, v_earth = _earth_wind(u[slug].value, v[slug].value, u[slug].longitude)
            winds[slug] = wind_from_uv(u_earth, v_earth)
        return winds

    terrain = record_values(first_forecast_hour, "HGT", "surface")
    model_elevation_by_site = {
        site["slug"]: _required_value(terrain[site["slug"]].value, "model elevation", site)
        for site in sites
    }

    hours_by_site: dict[str, list[dict]] = {
        site["slug"]: [_empty_hour(slot["validAt"]) for slot in forecast_slots] for site in sites
    }

    def surface_task(hour_index: int, field_name: str, variable: str, level: str, convert):
        def run_task() -> None:
            values = record_values(forecast_slots[hour_index]["forecastHour"], variable, level)
            for site in sites:
                hour = hours_by_site[site["slug"]][hour_index]
                hour[field_name] = convert(
                    _required_value(values[site["slug"]].value, field_name, site)
                )

        return run_task

    def temperature_task(hour_index: int):
        def run_task() -> None:
            forecast_hour = forecast_slots[hour_index]["forecastHour"]
            temperature = record_values(forecast_hour, "TMP", "2 m above ground")
            dew_point = record_values(forecast_hour, "DPT", "2 m above ground")
            for site in sites:
                slug = site["slug"]
                t = _required_value(temperature[slug].value, "temperatureC", site)
                d = _required_value(dew_point[slug].value, "dewPointDepressionC", site)
                hour = hours_by_site[slug][hour_index]
                hour["temperatureC"] = t - KELVIN
                hour["dewPointDepressionC"] = t - d

        return run_task

    def surface_wind_task(hour_index: int):
        def run_task() -> None:
            winds = wind_values(forecast_slots[hour_index]["forecastHour"], "10 m above ground")
            for site in sites:
                slug = site["slug"]
                if winds[slug] is None:
                    raise RuntimeError(f"NOAA returned no 10 m wind for {site['name']}")
                hour = hours_by_site[slug][hour_index]
                hour["windSpeedMs"], hour["windDirectionDeg"] = winds[slug]

        return run_task

    def pressure_task(hour_index: int, pressure_hpa: int):
        def run_task() -> None:
            forecast_hour = forecast_slots[hour_index]["forecastHour"]
            level = f"{pressure_hpa} mb"
            temperature = record_values(forecast_hour, "TMP", level)
            dew_point = record_values(forecast_hour, "DPT", level)
            height = record_values(forecast_hour, "HGT", level)
            winds = wind_values(forecast_hour, level)
            for site in sites:
                slug = site["slug"]
                t = temperature[slug].value
                d = dew_point[slug].value
                h = height[slug].value
                wind = winds[slug]
                if t is None or d is None or h is None or wind is None:
                    continue
                hours_by_site[slug][hour_index]["levels"][pressure_hpa] = {
                    "pressureHpa": pressure_hpa,
                    "heightM": h,
                    "temperatureC": t - KELVIN,
                    "dewPointDepressionC": t - d,
                    "windDirectionDeg": wind[1],
                    "windSpeedMs": wind[0],
                }

        return run_task

    def tasks_for_hour(hour_index: int) -> list:
        tasks = [temperature_task(hour_index), surface_wind_task(hour_index)]
        tasks += [
            surface_task(hour_index, field_name, variable, level, convert)
            for field_name, (variable, level, convert) in SURFACE_FIELDS.items()
        ]
        tasks += [pressure_task(hour_index, level) for level in PRESSURE_LEVELS]
        return tasks

    _run_concurrent(
        [task for index in range(len(forecast_slots)) for task in tasks_for_hour(index)]
    )

    generated_at = _instant()
    profiles = []
    for site in sites:
        source_hours = []
        for hour in hours_by_site[site["slug"]]:
            levels = sorted(
                (level for level in hour["levels"].values() if _is_complete_level(level)),
                key=lambda level: level["heightM"],
            )
            if len(levels) < 3:
                raise RuntimeError(f"NOAA returned too few pressure levels for {site['name']}")
            source_hours.append({**hour, "levels": levels})
        profiles.append(
            derive_windgram_profile(
                {
                    "generatedAt": generated_at,
                    "hours": source_hours,
                    "modelElevationM": model_elevation_by_site[site["slug"]],
                    "referenceTime": reference_time,
                    "siteAltitudeM": site["elevationM"],
                    "siteId": site["slug"],
                    "siteName": site["name"],
                },
                model=MODEL,
            )
        )
    return {
        "firstForecastHour": first_forecast_hour,
        "forecastHours": len(forecast_slots),
        "lastForecastHour": forecast_slots[-1]["forecastHour"],
        "profiles": profiles,
    }


def _grid_rotation_deg(longitude: float) -> float:
    """The angle from grid north to true north at a gridpoint's longitude.

    On a Lambert conformal grid the y-axis parallels the orientation
    meridian everywhere, so true north diverges from grid north by the cone
    constant times the longitude difference. Skipping this biases wind
    directions by 10–15° over the catalogued sites.
    """
    delta = (longitude - _LAMBERT_ORIENTATION_DEG + 180) % 360 - 180
    return _LAMBERT_CONE * delta


def _earth_wind(u_grid: float, v_grid: float, longitude: float) -> tuple[float, float]:
    angle = math.radians(_grid_rotation_deg(longitude))
    u_earth = u_grid * math.cos(angle) + v_grid * math.sin(angle)
    v_earth = -u_grid * math.sin(angle) + v_grid * math.cos(angle)
    return u_earth, v_earth


def _empty_hour(valid_at: str) -> dict:
    return {
        "cloudCoverPercent": math.nan,
        "dewPointDepressionC": math.nan,
        "latentHeatFluxWm2": math.nan,
        "levels": {},
        "precipitationMm": math.nan,
        "pressurePa": math.nan,
        "sensibleHeatFluxWm2": math.nan,
        "temperatureC": math.nan,
        "validAt": valid_at,
        "windDirectionDeg": math.nan,
        "windSpeedMs": math.nan,
    }


_LEVEL_FIELDS = (
    "pressureHpa",
    "heightM",
    "temperatureC",
    "dewPointDepressionC",
    "windDirectionDeg",
    "windSpeedMs",
)


def _is_complete_level(level: dict) -> bool:
    return all(field in level for field in _LEVEL_FIELDS)


def _required_value(value: float | None, field_name: str, site: dict) -> float:
    if value is None or not math.isfinite(value):
        raise RuntimeError(f"NOAA returned no {field_name} for {site['name']}")
    return value


def _max_steps() -> int | None:
    raw = os.environ.get("WINDGRAMS_MAX_STEPS")
    return int(raw) if raw else None


def _valid_time(reference_time: str, forecast_hour: int) -> str:
    instant = datetime.fromisoformat(reference_time.replace("Z", "+00:00")) + timedelta(
        hours=forecast_hour
    )
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def _instant() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _run_concurrent(tasks: list) -> None:
    with ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as executor:
        futures = [executor.submit(task) for task in tasks]
        try:
            for future in futures:
                future.result()
        except BaseException:
            executor.shutdown(cancel_futures=True)
            raise


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 — the workflow wants the message, not a trace
        print(error, file=sys.stderr)
        sys.exit(1)
