"""Builds windgram profiles for every catalogued site from the latest run of
a GeoMet-served model and writes them under the model's output directory.
Exits without touching the output when the latest run is already published,
so the workflow only commits real updates.

Run as a module it builds the HRDPS 2.5 km baseline; windgrams.build_rdps
and windgrams.build_gdps are the other models' entry points.
"""

from __future__ import annotations

import json
import math
import sys
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .publish import append_history, write_json
from .geomet import (
    HRDPS,
    PRESSURE_FIELDS,
    Bounds,
    CoverageUnavailableError,
    GeoMetModel,
    GeoMetRequestStats,
    fetch_coverage_grid,
    latest_reference_time,
)
from .windgram import (
    WINDGRAM_PRESSURE_LEVELS,
    derive_windgram_profile,
    windgram_display_hours,
)

FETCH_CONCURRENCY = 5
BOUNDS_MARGIN_DEGREES = 0.06


def main(model: GeoMetModel = HRDPS) -> None:
    sites = json.loads(Path("sites.json").read_text())
    if not sites:
        raise RuntimeError("sites.json is empty")

    stats = GeoMetRequestStats()
    reference_time = latest_reference_time(model, stats)
    if _published_reference_time(model) == reference_time:
        print(f"{model.name} run {reference_time} is already published.")
        return

    print(f"Building {model.name} {reference_time} for {len(sites)} sites…")
    started_at = time.monotonic()
    result = _build_profiles(model, reference_time, sites, stats)

    sites_dir = model.out_dir / "sites"
    sites_dir.mkdir(parents=True, exist_ok=True)
    for profile in result["profiles"]:
        write_json(sites_dir / f"{profile['siteId']}.json", profile, compact=True)
        append_history(profile, model.out_dir / "history")
    manifest = {
        "firstForecastHour": result["firstForecastHour"],
        "forecastHours": result["forecastHours"],
        "generatedAt": _instant(),
        "lastForecastHour": result["lastForecastHour"],
        "model": model.name,
        "referenceTime": reference_time,
        "sites": [{"name": site["name"], "slug": site["slug"]} for site in sites],
        "stats": {
            "durationMs": round((time.monotonic() - started_at) * 1000),
            "geoMetRequests": stats.requests,
            "geoMetResponseBytes": stats.response_bytes,
            "geoMetRetries": stats.retries,
        },
    }
    write_json(model.out_dir / "manifest.json", manifest, compact=False)
    print(
        f"Published {len(result['profiles'])} profiles for {reference_time} "
        f"({stats.requests} GeoMet requests, {stats.response_bytes // 1024} KiB)."
    )


def _published_reference_time(model: GeoMetModel) -> str | None:
    try:
        return json.loads((model.out_dir / "manifest.json").read_text())["referenceTime"]
    except (OSError, KeyError, ValueError):
        return None


def _build_profiles(
    model: GeoMetModel, reference_time: str, sites: list[dict], stats: GeoMetRequestStats
) -> dict:
    bounds = _bounds_for_sites(sites)

    def fetch_grid(layer: str, valid_at: str):
        return fetch_coverage_grid(
            bounds=bounds,
            layer=layer,
            reference_time=reference_time,
            resolution_deg=model.resolution_deg,
            stats=stats,
            valid_at=valid_at,
        )

    terrain = fetch_grid(model.terrain_layer, reference_time)
    model_elevation_by_site = {
        site["slug"]: _required_value(
            terrain.value_at(site["latitude"], site["longitude"]), "model elevation", site
        )
        for site in sites
    }

    forecast_slots = windgram_display_hours(
        [
            {"forecastHour": hour, "validAt": _valid_time(reference_time, hour)}
            for hour in model.forecast_hours
        ],
        model.min_hours_per_day,
    )
    hours_by_site = {
        site["slug"]: [_empty_hour(slot["validAt"]) for slot in forecast_slots] for site in sites
    }

    def surface_task(hour_index: int, field: str, layer: str):
        def run() -> None:
            grid = fetch_grid(layer, forecast_slots[hour_index]["validAt"])
            for site in sites:
                hour = hours_by_site[site["slug"]][hour_index]
                hour[field] = _required_value(
                    grid.value_at(site["latitude"], site["longitude"]), field, site
                )

        return run

    def pressure_task(hour_index: int, field: str, pressure_hpa: int):
        def run() -> None:
            try:
                grid = fetch_grid(
                    model.pressure_layer(field, pressure_hpa),
                    forecast_slots[hour_index]["validAt"],
                )
            except CoverageUnavailableError:
                # Some levels thin out late in a run (GDPS publishes six of
                # the nine 6-hourly beyond 168 h); a level absent at this
                # valid time simply stays out of the column.
                return
            for site in sites:
                value = grid.value_at(site["latitude"], site["longitude"])
                if value is None:
                    continue
                levels = hours_by_site[site["slug"]][hour_index]["levels"]
                levels.setdefault(pressure_hpa, {"pressureHpa": pressure_hpa})[field] = value

        return run

    # Run-total precipitation accumulations by forecast hour, sampled at the
    # sites. Hour 0 is the start of the run: nothing has accumulated yet.
    accumulation_lock = threading.Lock()
    accumulated_by_hour: dict[int, dict[str, float]] = {
        0: {site["slug"]: 0.0 for site in sites}
    }

    def accumulated_precip(forecast_hour: int) -> dict[str, float]:
        with accumulation_lock:
            cached = accumulated_by_hour.get(forecast_hour)
        if cached is not None:
            return cached
        # Two tasks racing on the same hour fetch it twice; that is harmless.
        grid = fetch_grid(
            model.precip_accumulation_layer, _valid_time(reference_time, forecast_hour)
        )
        values = {
            site["slug"]: _required_value(
                grid.value_at(site["latitude"], site["longitude"]), "precipitationMm", site
            )
            for site in sites
        }
        with accumulation_lock:
            accumulated_by_hour[forecast_hour] = values
        return values

    def precip_task(hour_index: int):
        def run() -> None:
            forecast_hour = forecast_slots[hour_index]["forecastHour"]
            precip = _precip_for_hour(accumulated_precip, model.forecast_hours, forecast_hour)
            for site in sites:
                hours_by_site[site["slug"]][hour_index]["precipitationMm"] = precip[site["slug"]]

        return run

    def tasks_for_hour(hour_index: int) -> list:
        tasks = [
            surface_task(hour_index, field, layer)
            for field, layer in model.surface_layers.items()
        ]
        if model.precip_accumulation_layer:
            tasks.append(precip_task(hour_index))
        for pressure_hpa in WINDGRAM_PRESSURE_LEVELS:
            for field in PRESSURE_FIELDS:
                tasks.append(pressure_task(hour_index, field, pressure_hpa))
        return tasks

    # The last hour first: a run GeoMet has only partially published fails
    # before ~1,600 requests, not after.
    last_hour_index = len(forecast_slots) - 1
    _run_concurrent(tasks_for_hour(last_hour_index))
    _run_concurrent(
        [task for index in range(last_hour_index) for task in tasks_for_hour(index)]
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
                raise RuntimeError(f"GeoMet returned too few pressure levels for {site['name']}")
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
                model=model.name,
            )
        )
    return {
        "firstForecastHour": forecast_slots[0]["forecastHour"],
        "forecastHours": len(forecast_slots),
        "lastForecastHour": forecast_slots[last_hour_index]["forecastHour"],
        "profiles": profiles,
    }


def _previous_scheduled_hour(schedule: Sequence[int], forecast_hour: int) -> int:
    """The schedule step before forecast_hour; 0 (run start) before the first."""
    index = schedule.index(forecast_hour)
    return schedule[index - 1] if index else 0


def _precip_for_hour(
    accumulated: Callable[[int], dict[str, float]],
    schedule: Sequence[int],
    forecast_hour: int,
) -> dict[str, float]:
    """Precipitation over one schedule step, differenced from run totals.

    The result is mm per step (3 h for GDPS), published as the column's
    precipitationMm — a per-column quantity, like the 1 km build's per-hour
    approximation from an instantaneous rate.
    """
    current = accumulated(forecast_hour)
    previous = accumulated(_previous_scheduled_hour(schedule, forecast_hour))
    return {slug: max(0.0, current[slug] - previous[slug]) for slug in current}


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


def _required_value(value: float | None, field: str, site: dict) -> float:
    if value is None or not math.isfinite(value):
        raise RuntimeError(f"GeoMet returned no {field} for {site['name']}")
    return value


def _bounds_for_sites(sites: list[dict]) -> Bounds:
    latitudes = [site["latitude"] for site in sites]
    longitudes = [site["longitude"] for site in sites]
    return Bounds(
        east=max(longitudes) + BOUNDS_MARGIN_DEGREES,
        north=max(latitudes) + BOUNDS_MARGIN_DEGREES,
        south=min(latitudes) - BOUNDS_MARGIN_DEGREES,
        west=min(longitudes) - BOUNDS_MARGIN_DEGREES,
    )


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


def run(model: GeoMetModel) -> None:
    try:
        main(model)
    except Exception as error:  # noqa: BLE001 — the workflow wants the message, not a trace
        print(error, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run(HRDPS)
