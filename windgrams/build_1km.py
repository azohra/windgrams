"""Builds windgram profiles from the experimental HRDPS West 1 km model.

The 1 km product has no GeoMet/WCS access: it publishes whole-domain GRIB2
files on the alpha Datamart (00Z and 12Z, 48 h, ~24 h retention), so this
builder downloads each needed field, samples the catalogued launch points,
and feeds the same derivation as the 2.5 km build. The feed is experimental
and does go dark; consumers are expected to fall back to 2.5 km.
"""

from __future__ import annotations

import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .datamart import DownloadStats, exists, fetch_bytes
from .grib import GribField
from .publish import append_history, write_json
from .windgram import derive_windgram_profile, windgram_display_hours

MODEL = "HRDPS West 1 km"
BASE_URL = "https://dd.alpha.weather.gc.ca/model_hrdps/west/1km/grib2"
OUT_DIR = Path("data/hrdps-1km-west")
RUN_HOURS = ("12", "00")
FORECAST_HOURS = 48
FETCH_CONCURRENCY = 4

KELVIN = 273.15
# GRIB names → source-hour fields, with unit conversions. PRATE is an
# instantaneous rate (kg/m²/s); ×3600 approximates the 2.5 km build's
# quantity-per-hour precipitation.
SURFACE_FIELDS = {
    "cloudCoverPercent": ("TCDC_SFC_0", lambda v: v),
    "dewPointDepressionC": ("DEPR_TGL_2", lambda v: v),
    "latentHeatFluxWm2": ("LHTFL_SFC_0", lambda v: v),
    "precipitationMm": ("PRATE_SFC_0", lambda v: v * 3600),
    "pressurePa": ("PRMSL_MSL_0", lambda v: v),
    "sensibleHeatFluxWm2": ("SHTFL_SFC_0", lambda v: v),
    "temperatureC": ("TMP_TGL_2", lambda v: v - KELVIN),
    "windDirectionDeg": ("WDIR_TGL_10", lambda v: v),
    "windSpeedMs": ("WIND_TGL_10", lambda v: v),
}
PRESSURE_FIELDS = {
    "dewPointDepressionC": ("DEPR", lambda v: v),
    "heightM": ("HGT", lambda v: v),
    "temperatureC": ("TMP", lambda v: v - KELVIN),
    "windDirectionDeg": ("WDIR", lambda v: v),
    "windSpeedMs": ("WIND", lambda v: v),
}
PRESSURE_LEVELS = (925, 900, 875, 850, 800, 750, 700, 650, 600)
TERRAIN_VARIABLE = "HGT_SFC_0"


def main() -> None:
    sites = json.loads(Path("sites.json").read_text())
    if not sites:
        raise RuntimeError("sites.json is empty")

    run = _latest_complete_run()
    if run is None:
        print("No complete HRDPS 1 km run is available.")
        return
    date = run["date"]
    reference_time = f"{date[:4]}-{date[4:6]}-{date[6:]}T{run['hour']}:00:00Z"
    if _published_reference_time() == reference_time:
        print(f"1 km run {reference_time} is already published.")
        return

    print(f"Building 1 km {reference_time} for {len(sites)} sites…")
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
        f"Published {len(result['profiles'])} 1 km profiles for {reference_time} "
        f"({stats.requests} downloads, {stats.response_bytes // (1024 * 1024)} MiB)."
    )


def _latest_complete_run() -> dict | None:
    """A run is complete when its final forecast hour is on the Datamart."""
    now = datetime.now(timezone.utc)
    for day_offset in (0, 1):
        date = (now - timedelta(days=day_offset)).strftime("%Y%m%d")
        for hour in RUN_HOURS:
            probe = _file_url("TMP_TGL_2", date, hour, FORECAST_HOURS)
            if exists(probe):
                return {"date": date, "hour": hour}
    return None


def _file_url(variable: str, date: str, run_hour: str, forecast_hour: int) -> str:
    name = (
        f"CMC_hrdps_west_{variable}_rotated_latlon0.009x0.009_"
        f"{date}T{run_hour}Z_P{forecast_hour:03d}-00.grib2"
    )
    return f"{BASE_URL}/{run_hour}/{forecast_hour:03d}/{name}"


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

    first_forecast_hour = forecast_slots[0]["forecastHour"]
    model_elevation_by_site: dict[str, float] = {}

    def sample(variable: str, forecast_hour: int) -> dict[str, float | None]:
        data = fetch_bytes(_file_url(variable, run["date"], run["hour"], forecast_hour), stats)
        with GribField(data) as field:
            return {
                site["slug"]: field.value_at(site["latitude"], site["longitude"])
                for site in sites
            }

    terrain = sample(TERRAIN_VARIABLE, first_forecast_hour)
    for site in sites:
        model_elevation_by_site[site["slug"]] = _required_value(
            terrain[site["slug"]], "model elevation", site
        )

    hours_by_site: dict[str, list[dict]] = {
        site["slug"]: [_empty_hour(slot["validAt"]) for slot in forecast_slots] for site in sites
    }

    def surface_task(hour_index: int, field_name: str, variable: str, convert):
        def run_task() -> None:
            values = sample(variable, forecast_slots[hour_index]["forecastHour"])
            for site in sites:
                hour = hours_by_site[site["slug"]][hour_index]
                hour[field_name] = convert(
                    _required_value(values[site["slug"]], field_name, site)
                )

        return run_task

    def pressure_task(hour_index: int, field_name: str, prefix: str, level: int, convert):
        def run_task() -> None:
            values = sample(
                f"{prefix}_ISBL_{level:04d}", forecast_slots[hour_index]["forecastHour"]
            )
            for site in sites:
                value = values[site["slug"]]
                if value is None:
                    continue
                levels = hours_by_site[site["slug"]][hour_index]["levels"]
                levels.setdefault(level, {"pressureHpa": level})[field_name] = convert(value)

        return run_task

    def tasks_for_hour(hour_index: int) -> list:
        tasks = [
            surface_task(hour_index, field_name, variable, convert)
            for field_name, (variable, convert) in SURFACE_FIELDS.items()
        ]
        for level in PRESSURE_LEVELS:
            for field_name, (prefix, convert) in PRESSURE_FIELDS.items():
                tasks.append(pressure_task(hour_index, field_name, prefix, level, convert))
        return tasks

    # The last hour first: a run the Datamart has only partially published
    # fails before ~1,600 downloads, not after.
    last_hour_index = len(forecast_slots) - 1
    _run_concurrent(tasks_for_hour(last_hour_index))
    _run_concurrent([task for index in range(last_hour_index) for task in tasks_for_hour(index)])

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
                raise RuntimeError(f"Datamart returned too few pressure levels for {site['name']}")
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
        "lastForecastHour": forecast_slots[last_hour_index]["forecastHour"],
        "profiles": profiles,
    }


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
        raise RuntimeError(f"Datamart returned no {field_name} for {site['name']}")
    return value


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
