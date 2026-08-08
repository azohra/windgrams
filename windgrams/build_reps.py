"""Builds per-site ensemble JSON from ECCC's REPS 10 km ensemble.

Not a windgram: the output contextualizes the deterministic windgram with
per-hour percentiles of the derived scalars the profiles publish —
usable-lift top, boundary-layer top, thermal velocity, cloud base, 10 m wind
speed and the other site-level per-hour quantities. The physics rule: every
one of the 21 members is derived as its own atmosphere and the percentiles
are taken across the derived outputs — inputs are never averaged first,
because the mean of 21 atmospheres is not an atmosphere.

Schema semantics — the contract with consumers:
- Each scalar publishes {"members", "p10", "p25", "p50", "p75", "p90"}.
  Percentiles are conditional on the quantity being defined: a member with
  no boundary layer or no usable lift stays out of that scalar's ranking,
  not ranked at zero, and "members" says how many of the 21 contributed.
- boundaryLayerTopM and usableLiftTopM additionally publish
  "ceiledMembers": how many of the defined members were clamped at the top
  of their own column because the parcel was still buoyant at the highest
  level. When it is nonzero, the percentiles are lower bounds, not
  measurements.
- Renderer guidance: with fewer than about half the members defined, show
  the defined fraction rather than a band; with ceiledMembers nonzero,
  label the band a floor, never a ceiling.
- Wind direction is circular and is deliberately not aggregated.

REPS carries only three of the nine windgram pressure levels (925/850/700).
Each member's column is fed honestly with those plus 500 hPa — not a
windgram display level, but real input the derivation accepts — so the
dry-parcel search has headroom above summer boundary layers (column top
~5,700 gpm instead of ~3,150). 925 hPa typically sits below REPS model
terrain at the catalogued sites and the derivation's own filter drops it.

Transport is hybrid, per the 2026-08-07 verification spike:
- GeoMet WCS crops for everything except winds. Member layers are suffixed
  REPS.MEM.<family>.NN with .01 the control. Fluxes are instantaneous W/m²;
  precipitation is a run-total accumulation differenced between 3 h steps;
  2 m and pressure-level dew point depressions are derived from T + RH
  (GeoMet's REPS members publish no dew point in any form).
- Datamart all-members GRIB2 for UGRD/VGRD (925/850/700/500 hPa + 10 m
  AGL): GeoMet has no per-member U/V, and REPS's rotated grid means the
  components are grid-relative (uvRelativeToGrid=1) — they are rotated to
  true east/north before the wind convention is applied.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .datamart import DownloadStats, exists, fetch_bytes
from .geomet import Bounds, GeoMetRequestStats, fetch_coverage_grid
from .grib import GribField, earth_wind, split_messages
from .moisture import dew_point_depression
from .noaa import wind_from_uv
from .publish import append_history, write_json
from .windgram import derive_windgram_profile, windgram_display_hours

MODEL = "REPS 10 km"
OUT_DIR = Path("data/reps-10km")
DATAMART_URL = "https://dd.weather.gc.ca"

MEMBER_COUNT = 21
PERTURBATION_NUMBERS = tuple(range(MEMBER_COUNT))
RUN_HOURS = ("18", "12", "06", "00")
STEP_HOURS = 3
LAST_FORECAST_HOUR = 72
FORECAST_HOURS = tuple(range(STEP_HOURS, LAST_FORECAST_HOUR + 1, STEP_HOURS))
# 3-hourly steps land five columns inside the display day (same as GDPS).
MIN_HOURS_PER_DAY = 4
FETCH_CONCURRENCY = 5
BOUNDS_MARGIN_DEGREES = 0.06
# Fine oversampling pins each sample to the model cell GetFeatureInfo reports
# (see the RDPS note in geomet.py); verified live against REPS member layers.
RESOLUTION_DEG = 0.0225

# GeoMet member layer families (units per capabilities: TT °C, HR %, NT %,
# PN-SLP Pa, PR mm run-total, FC/FV W/m², GZ gpm).
SURFACE_LAYER_FAMILIES = {
    "cloudCoverPercent": "REPS.MEM.ETA_NT",
    "latentHeatFluxWm2": "REPS.MEM.ETA_FV",
    "pressurePa": "REPS.MEM.ETA_PN-SLP",
    "relativeHumidityPercent": "REPS.MEM.ETA_HR",
    "sensibleHeatFluxWm2": "REPS.MEM.ETA_FC",
    "temperatureC": "REPS.MEM.ETA_TT",
}
PRECIP_ACCUMULATION_FAMILY = "REPS.MEM.ETA_PR"
TERRAIN_FAMILY = "REPS.MEM.ETA_GZ"
PRESSURE_LAYER_FAMILIES = {
    "heightM": "REPS.MEM.PRES_GZ",
    "relativeHumidityPercent": "REPS.MEM.PRES_HR",
    "temperatureC": "REPS.MEM.PRES_TT",
}
PRESSURE_LEVELS = (925, 850, 700, 500)

# Datamart wind files: one file per variable/level/hour, all 21 members
# stacked. Level token → pressureHpa (None marks the 10 m surface wind).
WIND_LEVEL_TOKENS = {
    "AGL-10m": None,
    "ISBL-0925": 925,
    "ISBL-0850": 850,
    "ISBL-0700": 700,
    "ISBL-0500": 500,
}

PERCENTILE_POINTS = (10, 25, 50, 75, 90)
# The site-level per-hour scalars the profile publishes, minus circular wind
# direction (a percentile across bearings is meaningless), split around
# validAt to keep the hour dict's keys in the profile's sorted order.
SCALARS_BEFORE_VALID_AT = (
    "boundaryLayerTopM",
    "cloudBaseM",
    "cloudCoverPercent",
    "precipitationMm",
    "pressureKpa",
    "surfaceTemperatureC",
    "thermalVelocityMs",
    "usableLiftTopM",
)
SCALARS_AFTER_VALID_AT = ("windSpeedKmh",)
# Quantities the derivation clamps at the top of a member's column when the
# parcel is still buoyant at the highest level; their blocks carry a
# ceiledMembers count so consumers know when percentiles are lower bounds.
CENSORED_SCALARS = ("boundaryLayerTopM", "usableLiftTopM")
# Covers the float round-trip of elevation + (top − elevation); columns are
# 3-hourly so the profile's 1-hourly smoothing never moves a clamped value.
CEILING_TOLERANCE_M = 0.5


def member_layer(family: str, perturbation_number: int) -> str:
    """The GeoMet layer for a GRIB member. GeoMet suffixes are 1-based with
    .01 the control; GRIB2 perturbationNumber is 0-based with 0 the control,
    so suffix NN pairs with perturbationNumber NN−1. This is the only place
    the two numbering schemes may meet — a one-off here would silently
    decorrelate every member's column across the two transports."""
    return f"{family}.{perturbation_number + 1:02d}"


def percentile(sorted_values: list[float], point: float) -> float:
    """Percentile by linear interpolation between closest ranks (the sorted
    values are trusted, not re-sorted). With 21 members every published point
    lands on an exact rank: p10→2, p25→5, p50→10, p75→15, p90→18."""
    if not sorted_values:
        raise ValueError("percentile of no values")
    rank = (len(sorted_values) - 1) * point / 100
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[low]
    return sorted_values[low] + (rank - low) * (sorted_values[high] - sorted_values[low])


def main() -> None:
    arguments = _parse_arguments()
    sites = json.loads(Path("sites.json").read_text())
    if not sites:
        raise RuntimeError("sites.json is empty")

    if arguments.reference_time:
        reference_time = _canonical_instant(arguments.reference_time)
    else:
        reference_time = _latest_complete_run()
        if reference_time is None:
            print("No complete REPS run is available.")
            return
        if _published_reference_time() == reference_time:
            print(f"REPS run {reference_time} is already published.")
            return

    forecast_slots = [
        {"forecastHour": hour, "validAt": _valid_time(reference_time, hour)}
        for hour in _forecast_hours(arguments.steps)
    ]
    if arguments.steps is None:
        # Explicit step subsets are for testing and are honoured verbatim;
        # only the full schedule is trimmed to the pilots' day.
        forecast_slots = windgram_display_hours(forecast_slots, MIN_HOURS_PER_DAY)
    print(
        f"Building REPS ensemble {reference_time} for {len(sites)} sites "
        f"({len(forecast_slots)} steps × {MEMBER_COUNT} members)…"
    )
    started_at = time.monotonic()
    geomet_stats = GeoMetRequestStats()
    download_stats = DownloadStats()
    result = _build_documents(
        reference_time, forecast_slots, sites, geomet_stats, download_stats
    )

    sites_dir = OUT_DIR / "sites"
    sites_dir.mkdir(parents=True, exist_ok=True)
    for document in result["documents"]:
        write_json(sites_dir / f"{document['siteId']}.json", document, compact=True)
        append_history(document, OUT_DIR / "history")
    manifest = {
        "firstForecastHour": result["firstForecastHour"],
        "forecastHours": result["forecastHours"],
        "generatedAt": _instant(),
        "lastForecastHour": result["lastForecastHour"],
        "memberCount": MEMBER_COUNT,
        "model": MODEL,
        "referenceTime": reference_time,
        "sites": [{"name": site["name"], "slug": site["slug"]} for site in sites],
        "stats": {
            "downloadBytes": download_stats.response_bytes,
            "downloadRetries": download_stats.retries,
            "downloads": download_stats.requests,
            "durationMs": round((time.monotonic() - started_at) * 1000),
            "geoMetRequests": geomet_stats.requests,
            "geoMetResponseBytes": geomet_stats.response_bytes,
            "geoMetRetries": geomet_stats.retries,
        },
    }
    write_json(OUT_DIR / "manifest.json", manifest, compact=False)
    print(
        f"Published {len(result['documents'])} ensemble documents for {reference_time} "
        f"({geomet_stats.requests} GeoMet requests, "
        f"{geomet_stats.response_bytes // 1024} KiB; {download_stats.requests} downloads, "
        f"{download_stats.response_bytes // (1024 * 1024)} MiB)."
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--reference-time",
        help="build this run (e.g. 2026-08-07T12:00:00Z) instead of probing for "
        "the newest complete one; skips the already-published check",
    )
    parser.add_argument(
        "--steps",
        help="comma-separated forecast hours to build (e.g. 18,21,24) instead of "
        "the full display schedule",
    )
    return parser.parse_args()


def _forecast_hours(steps: str | None) -> tuple[int, ...]:
    if steps is None:
        return tuple(FORECAST_HOURS)
    hours = tuple(sorted(int(step) for step in steps.split(",")))
    for hour in hours:
        if hour not in FORECAST_HOURS:
            raise RuntimeError(f"forecast hour {hour} is not on the REPS 3-hourly schedule")
    return hours


def _latest_complete_run() -> str | None:
    """A run is complete when its final hour's 10 m wind is on the Datamart.
    The date directory is pre-created ahead of data, so only a HEAD of the
    file itself proves anything."""
    now = datetime.now(timezone.utc)
    for day_offset in (0, 1):
        date = (now - timedelta(days=day_offset)).strftime("%Y%m%d")
        for hour in RUN_HOURS:
            if day_offset == 0 and int(hour) > now.hour:
                continue
            if exists(_wind_file_url("UGRD", "AGL-10m", date, hour, LAST_FORECAST_HOUR)):
                return f"{date[:4]}-{date[4:6]}-{date[6:]}T{hour}:00:00Z"
    return None


def _wind_file_url(
    variable: str, level_token: str, date: str, run_hour: str, forecast_hour: int
) -> str:
    name = (
        f"{date}T{run_hour}Z_MSC_REPS_{variable}_{level_token}_"
        f"RLatLon0.09x0.09_PT{forecast_hour:03d}H.grib2"
    )
    return (
        f"{DATAMART_URL}/{date}/WXO-DD/ensemble/reps/10km/grib2/"
        f"{run_hour}/{forecast_hour:03d}/{name}"
    )


def _published_reference_time() -> str | None:
    try:
        return json.loads((OUT_DIR / "manifest.json").read_text())["referenceTime"]
    except (OSError, KeyError, ValueError):
        return None


def _build_documents(
    reference_time: str,
    forecast_slots: list[dict],
    sites: list[dict],
    geomet_stats: GeoMetRequestStats,
    download_stats: DownloadStats,
) -> dict:
    bounds = _bounds_for_sites(sites)
    run_date = reference_time[:10].replace("-", "")
    run_hour = reference_time[11:13]

    def fetch_grid(layer: str, valid_at: str):
        return fetch_coverage_grid(
            bounds=bounds,
            layer=layer,
            reference_time=reference_time,
            resolution_deg=RESOLUTION_DEG,
            stats=geomet_stats,
            valid_at=valid_at,
        )

    def sample_all_sites(grid, field: str, member: int) -> dict[str, float]:
        return {
            site["slug"]: _required_value(
                grid.value_at(site["latitude"], site["longitude"]), field, site, member
            )
            for site in sites
        }

    # Model terrain per member (the GZ layer exists only at the reference
    # instant, mirroring Datamart's HGT_SFC at PT000H).
    model_elevation: dict[int, dict[str, float]] = {}

    def terrain_task(member: int):
        def run_task() -> None:
            grid = fetch_grid(member_layer(TERRAIN_FAMILY, member), reference_time)
            model_elevation[member] = sample_all_sites(grid, "model elevation", member)

        return run_task

    # hours[slug][member][hour_index] → a windgram source hour in the making.
    hours: dict[str, dict[int, list[dict]]] = {
        site["slug"]: {
            member: [_empty_hour(slot["validAt"]) for slot in forecast_slots]
            for member in PERTURBATION_NUMBERS
        }
        for site in sites
    }

    def surface_task(hour_index: int, member: int, field: str, family: str):
        def run_task() -> None:
            grid = fetch_grid(
                member_layer(family, member), forecast_slots[hour_index]["validAt"]
            )
            values = sample_all_sites(grid, field, member)
            for site in sites:
                hours[site["slug"]][member][hour_index][field] = values[site["slug"]]

        return run_task

    def pressure_task(hour_index: int, member: int, field: str, pressure_hpa: int):
        def run_task() -> None:
            grid = fetch_grid(
                member_layer(f"{PRESSURE_LAYER_FAMILIES[field]}.{pressure_hpa}", member),
                forecast_slots[hour_index]["validAt"],
            )
            values = sample_all_sites(grid, f"{field}@{pressure_hpa}", member)
            for site in sites:
                levels = hours[site["slug"]][member][hour_index]["levels"]
                levels.setdefault(pressure_hpa, {"pressureHpa": pressure_hpa})[field] = values[
                    site["slug"]
                ]

        return run_task

    # Run-total precipitation per member, differenced between consecutive
    # 3-hourly steps (the GDPS pattern). Nothing has accumulated at hour 0.
    accumulation_lock = threading.Lock()
    accumulated: dict[tuple[int, int], dict[str, float]] = {
        (member, 0): {site["slug"]: 0.0 for site in sites}
        for member in PERTURBATION_NUMBERS
    }

    def accumulated_precip(member: int, forecast_hour: int) -> dict[str, float]:
        with accumulation_lock:
            cached = accumulated.get((member, forecast_hour))
        if cached is not None:
            return cached
        grid = fetch_grid(
            member_layer(PRECIP_ACCUMULATION_FAMILY, member),
            _valid_time(reference_time, forecast_hour),
        )
        values = sample_all_sites(grid, "precipitationMm", member)
        with accumulation_lock:
            accumulated[(member, forecast_hour)] = values
        return values

    def precip_task(hour_index: int, member: int):
        def run_task() -> None:
            forecast_hour = forecast_slots[hour_index]["forecastHour"]
            current = accumulated_precip(member, forecast_hour)
            previous = accumulated_precip(member, forecast_hour - STEP_HOURS)
            for site in sites:
                slug = site["slug"]
                hours[slug][member][hour_index]["precipitationMm"] = max(
                    0.0, current[slug] - previous[slug]
                )

        return run_task

    def wind_task(hour_index: int, level_token: str, pressure_hpa: int | None):
        def run_task() -> None:
            forecast_hour = forecast_slots[hour_index]["forecastHour"]
            u_members = _sample_wind_members(
                fetch_bytes(
                    _wind_file_url("UGRD", level_token, run_date, run_hour, forecast_hour),
                    download_stats,
                ),
                sites,
            )
            v_members = _sample_wind_members(
                fetch_bytes(
                    _wind_file_url("VGRD", level_token, run_date, run_hour, forecast_hour),
                    download_stats,
                ),
                sites,
            )
            for member in PERTURBATION_NUMBERS:
                for site in sites:
                    slug = site["slug"]
                    east, north = earth_wind(
                        u_members[member]["values"][slug],
                        v_members[member]["values"][slug],
                        site["latitude"],
                        site["longitude"],
                        u_members[member]["southPoleLatitude"],
                        u_members[member]["southPoleLongitude"],
                    )
                    speed, direction = wind_from_uv(east, north)
                    hour = hours[slug][member][hour_index]
                    if pressure_hpa is None:
                        hour["windSpeedMs"] = speed
                        hour["windDirectionDeg"] = direction
                    else:
                        level = hour["levels"].setdefault(
                            pressure_hpa, {"pressureHpa": pressure_hpa}
                        )
                        level["windSpeedMs"] = speed
                        level["windDirectionDeg"] = direction

        return run_task

    def tasks_for_hour(hour_index: int) -> list:
        tasks = []
        for member in PERTURBATION_NUMBERS:
            for field, family in SURFACE_LAYER_FAMILIES.items():
                tasks.append(surface_task(hour_index, member, field, family))
            tasks.append(precip_task(hour_index, member))
            for pressure_hpa in PRESSURE_LEVELS:
                for field in PRESSURE_LAYER_FAMILIES:
                    tasks.append(pressure_task(hour_index, member, field, pressure_hpa))
        for level_token, pressure_hpa in WIND_LEVEL_TOKENS.items():
            tasks.append(wind_task(hour_index, level_token, pressure_hpa))
        return tasks

    # The last hour first: a run only partially published on either transport
    # fails before ~5,000 requests, not after.
    last_hour_index = len(forecast_slots) - 1
    _run_concurrent([terrain_task(member) for member in PERTURBATION_NUMBERS])
    _run_concurrent(tasks_for_hour(last_hour_index))
    _run_concurrent([task for index in range(last_hour_index) for task in tasks_for_hour(index)])

    generated_at = _instant()
    documents = []
    for site in sites:
        member_profiles = [
            _derive_member_profile(
                site,
                hours[site["slug"]][member],
                model_elevation[member][site["slug"]],
                reference_time,
                generated_at,
            )
            for member in PERTURBATION_NUMBERS
        ]
        documents.append(
            {
                "generatedAt": generated_at,
                "memberCount": MEMBER_COUNT,
                "model": MODEL,
                "modelElevationM": model_elevation[0][site["slug"]],
                "referenceTime": reference_time,
                "siteAltitudeM": site["elevationM"],
                "siteId": site["slug"],
                "siteName": site["name"],
                "hours": _aggregate_hours(member_profiles),
            }
        )
    return {
        "firstForecastHour": forecast_slots[0]["forecastHour"],
        "forecastHours": len(forecast_slots),
        "lastForecastHour": forecast_slots[last_hour_index]["forecastHour"],
        "documents": documents,
    }


def _derive_member_profile(
    site: dict,
    member_hours: list[dict],
    model_elevation_m: float,
    reference_time: str,
    generated_at: str,
) -> dict:
    """One member's windgram profile, from its own column — the derivation
    runs 21 times per site, never on averaged inputs."""
    source_hours = []
    for hour in member_hours:
        levels = sorted(hour["levels"].values(), key=lambda level: level["pressureHpa"])
        incomplete = [
            level["pressureHpa"] for level in levels if not _is_complete_level(level)
        ]
        if len(levels) != len(PRESSURE_LEVELS) or incomplete:
            raise RuntimeError(
                f"REPS column for {site['name']} at {hour['validAt']} is missing "
                f"level data ({incomplete or 'whole levels'})"
            )
        hour = dict(hour)
        hour["dewPointDepressionC"] = dew_point_depression(
            hour["temperatureC"], hour.pop("relativeHumidityPercent")
        )
        source_hours.append(
            {
                **hour,
                "levels": [
                    _with_dew_point_depression(level)
                    for level in sorted(levels, key=lambda level: level["heightM"])
                ],
            }
        )
    return derive_windgram_profile(
        {
            "generatedAt": generated_at,
            "hours": source_hours,
            "modelElevationM": model_elevation_m,
            "referenceTime": reference_time,
            "siteAltitudeM": site["elevationM"],
            "siteId": site["slug"],
            "siteName": site["name"],
        },
        model=MODEL,
    )


def _with_dew_point_depression(level: dict) -> dict:
    level = dict(level)
    level["dewPointDepressionC"] = dew_point_depression(
        level["temperatureC"], level.pop("relativeHumidityPercent")
    )
    return level


def _aggregate_hours(member_profiles: list[dict]) -> list[dict]:
    """Percentiles across the members' derived hours. A member whose scalar
    is null (no boundary layer, no usable lift) is left out of that scalar's
    ranking; the members count says how many contributed."""
    aggregated_hours = []
    for hour_index in range(len(member_profiles[0]["hours"])):
        member_hours = [profile["hours"][hour_index] for profile in member_profiles]
        aggregated: dict = {}
        for key in SCALARS_BEFORE_VALID_AT:
            aggregated[key] = _scalar_block(member_hours, key)
        aggregated["validAt"] = member_hours[0]["validAt"]
        for key in SCALARS_AFTER_VALID_AT:
            aggregated[key] = _scalar_block(member_hours, key)
        aggregated_hours.append(aggregated)
    return aggregated_hours


def _scalar_block(member_hours: list[dict], key: str) -> dict:
    block = _percentile_block([hour[key] for hour in member_hours])
    if key in CENSORED_SCALARS:
        return {"ceiledMembers": _ceiled_members(member_hours, key), **block}
    return block


def _ceiled_members(member_hours: list[dict], key: str) -> int:
    """How many defined members were censored at the top of their own column
    — the derivation clamps there when the parcel is still buoyant at the
    highest level, so the member's value is a floor, not a measurement."""
    count = 0
    for hour in member_hours:
        value = hour[key]
        levels = hour["levels"]
        if value is None or not levels:
            continue
        if value >= levels[-1]["heightM"] - CEILING_TOLERANCE_M:
            count += 1
    return count


def _percentile_block(values: list[float | None]) -> dict:
    present = sorted(value for value in values if value is not None)
    block: dict = {"members": len(present)}
    for point in PERCENTILE_POINTS:
        block[f"p{point}"] = percentile(present, point) if present else None
    return block


def _sample_wind_members(data: bytes, sites: list[dict]) -> dict[int, dict]:
    """Per-member site samples from an all-members Datamart file, keyed by
    GRIB perturbationNumber, with the grid's rotation pole alongside."""
    members: dict[int, dict] = {}
    for message in split_messages(data):
        with GribField(message) as field:
            if field.metadata("gridType") != "rotated_ll":
                raise RuntimeError("REPS wind file is not on the rotated grid")
            if float(field.metadata("angleOfRotationInDegrees")) != 0.0:
                raise RuntimeError("REPS wind grid has an unexpected rotation angle")
            if int(field.metadata("uvRelativeToGrid")) != 1:
                raise RuntimeError("REPS wind components are unexpectedly earth-relative")
            member = int(field.metadata("perturbationNumber"))
            members[member] = {
                "southPoleLatitude": float(
                    field.metadata("latitudeOfSouthernPoleInDegrees")
                ),
                "southPoleLongitude": float(
                    field.metadata("longitudeOfSouthernPoleInDegrees")
                ),
                "values": {
                    site["slug"]: _required_value(
                        field.value_at(site["latitude"], site["longitude"]),
                        "wind component",
                        site,
                        member,
                    )
                    for site in sites
                },
            }
    if sorted(members) != list(PERTURBATION_NUMBERS):
        raise RuntimeError(
            f"REPS wind file carries members {sorted(members)}, expected 0–20"
        )
    return members


def _empty_hour(valid_at: str) -> dict:
    return {
        "cloudCoverPercent": math.nan,
        "latentHeatFluxWm2": math.nan,
        "levels": {},
        "precipitationMm": math.nan,
        "pressurePa": math.nan,
        "relativeHumidityPercent": math.nan,
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
    "relativeHumidityPercent",
    "windDirectionDeg",
    "windSpeedMs",
)


def _is_complete_level(level: dict) -> bool:
    return all(field in level for field in _LEVEL_FIELDS)


def _required_value(value: float | None, field: str, site: dict, member: int) -> float:
    if value is None or not math.isfinite(value):
        raise RuntimeError(f"No {field} for {site['name']} (member {member})")
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


def _canonical_instant(value: str) -> str:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
