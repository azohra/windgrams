"""GeoMet WCS client: latest model run discovery, tiny GeoTIFF crops, and
the configurations of the models this pipeline builds from GeoMet.

Retries 429s and 5xx with jittered backoff, honours Retry-After, and counts
every request so the manifest can report what a build cost upstream.
"""

from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

import requests

from .geotiff import GeoTiffGrid, parse_geotiff_grid

GEOMET_URL = "https://geo.weather.gc.ca/geomet"
USER_AGENT = "Windgrams/2.0 (+https://github.com/azohra/windgrams)"

SURFACE_LAYERS = {
    "cloudCoverPercent": "HRDPS.CONTINENTAL_NT",
    "dewPointDepressionC": "HRDPS.CONTINENTAL_ES",
    "latentHeatFluxWm2": "HRDPS.CONTINENTAL_FV",
    "precipitationMm": "HRDPS.CONTINENTAL.DIAG_PR_PT1H",
    "pressurePa": "HRDPS.CONTINENTAL_PN-SLP",
    "sensibleHeatFluxWm2": "HRDPS.CONTINENTAL_FC",
    "temperatureC": "HRDPS.CONTINENTAL_TT",
    "windDirectionDeg": "HRDPS.CONTINENTAL_WD",
    "windSpeedMs": "HRDPS.CONTINENTAL_WSPD",
}

PRESSURE_LAYER_FIELDS = {
    "dewPointDepressionC": "PRES_ES",
    "heightM": "PRES_GZ",
    "temperatureC": "PRES_TT",
    "windDirectionDeg": "PRES_WD",
    "windSpeedMs": "PRES_WSPD",
}

# The pressure-level fields every model must provide, in fetch order.
PRESSURE_FIELDS = tuple(PRESSURE_LAYER_FIELDS)

# RDPS and GDPS use GeoMet's newer layer naming: <model>_<Field>[_<level>].
NEW_STYLE_PRESSURE_FIELDS = {
    "dewPointDepressionC": "DewPointDepression",
    "heightM": "GeopotentialHeight",
    "temperatureC": "AirTemp",
    "windDirectionDeg": "WindDir",
    "windSpeedMs": "WindSpeed",
}

REQUEST_TIMEOUT_S = 15
MAX_RETRY_DELAY_S = 10


class CoverageUnavailableError(RuntimeError):
    """GeoMet has no coverage for this layer at the requested valid time."""


@dataclass
class GeoMetRequestStats:
    requests: int = 0
    response_bytes: int = 0
    retries: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_request(self, retry: bool) -> None:
        with self._lock:
            self.requests += 1
            if retry:
                self.retries += 1

    def record_bytes(self, count: int) -> None:
        with self._lock:
            self.response_bytes += count


@dataclass(frozen=True)
class Bounds:
    east: float
    north: float
    south: float
    west: float


@dataclass(frozen=True)
class GeoMetModel:
    """Everything model-specific a build needs: layer names, the native grid
    resolution, the forecast schedule, and where the output publishes."""

    name: str
    capabilities_layer: str
    surface_layers: dict[str, str]
    pressure_layer: Callable[[str, int], str]
    terrain_layer: str
    resolution_deg: float
    forecast_hours: tuple[int, ...]
    out_dir: Path
    min_hours_per_day: int = 5
    # Run-total accumulation layer, differenced between scheduled steps, for
    # models without a fixed-window precipitation layer.
    precip_accumulation_layer: str | None = None


def pressure_layer(field_name: str, pressure_hpa: int) -> str:
    return f"HRDPS.CONTINENTAL.{PRESSURE_LAYER_FIELDS[field_name]}.{pressure_hpa}"


def new_style_pressure_layer(prefix: str) -> Callable[[str, int], str]:
    def layer(field_name: str, pressure_hpa: int) -> str:
        return f"{prefix}_{NEW_STYLE_PRESSURE_FIELDS[field_name]}_{pressure_hpa}mb"

    return layer


HRDPS = GeoMetModel(
    name="HRDPS continental 2.5 km",
    capabilities_layer="HRDPS.CONTINENTAL.PRES_TT.850",
    surface_layers=SURFACE_LAYERS,
    pressure_layer=pressure_layer,
    terrain_layer="HRDPS.CONTINENTAL_GZ",
    resolution_deg=0.0225,
    forecast_hours=tuple(range(1, 49)),
    out_dir=Path("data/hrdps-2p5km"),
)

RDPS = GeoMetModel(
    name="RDPS regional 10 km",
    capabilities_layer="RDPS_10km_AirTemp_850mb",
    surface_layers={
        "cloudCoverPercent": "RDPS_10km_TotalCloudCover",
        "dewPointDepressionC": "RDPS_10km_DewPointDepression_2m",
        "latentHeatFluxWm2": "RDPS_10km_LatentHeatNetFlux",
        "precipitationMm": "RDPS_10km_Precip-Accum1h",
        "pressurePa": "RDPS_10km_Pressure_MSL",
        "sensibleHeatFluxWm2": "RDPS_10km_SensibleHeatNetFlux",
        "temperatureC": "RDPS_10km_AirTemp_2m",
        "windDirectionDeg": "RDPS_10km_WindDir_10m",
        "windSpeedMs": "RDPS_10km_WindSpeed_10m",
    },
    pressure_layer=new_style_pressure_layer("RDPS_10km"),
    terrain_layer="RDPS_10km_GeopotentialHeight",
    # Not the model's 10 km spacing: GeoMet stretches whatever RESOLUTION it
    # gets to fit the subset, so asking for ~native shifts nearest-cell
    # samples up to a whole model cell. A fine grid pins each sample to the
    # cell GetFeatureInfo reports (verified live against it).
    resolution_deg=0.0225,
    forecast_hours=tuple(range(1, 85)),
    out_dir=Path("data/rdps-10km"),
)

GDPS = GeoMetModel(
    name="GDPS global 15 km",
    capabilities_layer="GDPS_15km_AirTemp_850mb",
    surface_layers={
        "cloudCoverPercent": "GDPS_15km_TotalCloudCover",
        "dewPointDepressionC": "GDPS_15km_DewPointDepression_2m",
        "latentHeatFluxWm2": "GDPS_15km_LatentHeatNetFlux",
        "pressurePa": "GDPS_15km_Pressure_MSL",
        "sensibleHeatFluxWm2": "GDPS_15km_SensibleHeatNetFlux",
        "temperatureC": "GDPS_15km_AirTemp_2m",
        "windDirectionDeg": "GDPS_15km_WindDir_10m",
        "windSpeedMs": "GDPS_15km_WindSpeed_10m",
    },
    pressure_layer=new_style_pressure_layer("GDPS_15km"),
    terrain_layer="GDPS_15km_GeopotentialHeight",
    # Fine for the same reason as RDPS: it keeps samples on the model's own
    # cells despite GeoMet stretching the grid to fit the subset.
    resolution_deg=0.0225,
    # Surface layers and levels 925/850/700 are 3-hourly across the whole
    # 240 h horizon; the other levels drop to 6-hourly after 168 h and just
    # go missing from the columns in between.
    forecast_hours=tuple(range(3, 241, 3)),
    out_dir=Path("data/gdps-15km"),
    # 3-hourly steps land exactly five columns inside the 07:00–21:00 display
    # window, so the default minimum would drop a day over one missing step.
    min_hours_per_day=4,
    # No fixed-window precipitation layer spans 240 h; difference the
    # run-total accumulation between scheduled steps instead.
    precip_accumulation_layer="GDPS_15km_Precip-Accum",
)


_session_local = threading.local()


def _session() -> requests.Session:
    session = getattr(_session_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
        _session_local.session = session
    return session


def latest_reference_time(model: GeoMetModel, stats: GeoMetRequestStats | None = None) -> str:
    query = {
        "LAYERS": model.capabilities_layer,
        "REQUEST": "GetCapabilities",
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
    }
    response = _fetch_geomet(f"{GEOMET_URL}?{urlencode(query)}", stats)
    if response.status_code != 200:
        raise RuntimeError(f"GeoMet capabilities failed with {response.status_code}")
    if stats:
        stats.record_bytes(len(response.content))
    return parse_latest_reference_time(response.text, model.name)


def parse_latest_reference_time(xml: str, model_name: str = "HRDPS") -> str:
    dimension = re.search(r"<Dimension\b[^>]*name=\"reference_time\"[^>]*>", xml, re.IGNORECASE)
    reference_time = None
    if dimension:
        default = re.search(r"\bdefault=\"([^\"]+)\"", dimension.group(0), re.IGNORECASE)
        if default:
            reference_time = default.group(1)
    if not reference_time or not _parses_as_instant(reference_time):
        raise RuntimeError(f"GeoMet did not advertise a current {model_name} run")
    return reference_time


def fetch_coverage_grid(
    *,
    bounds: Bounds,
    layer: str,
    reference_time: str,
    resolution_deg: float,
    stats: GeoMetRequestStats | None = None,
    valid_at: str,
) -> GeoTiffGrid:
    query = [
        ("COVERAGEID", layer),
        ("DIM_REFERENCE_TIME", reference_time),
        ("FORMAT", "image/tiff"),
        ("OUTPUTCRS", "EPSG:4326"),
        ("REQUEST", "GetCoverage"),
        ("RESOLUTION", f"x({resolution_deg})"),
        ("SERVICE", "WCS"),
        ("SUBSETTINGCRS", "EPSG:4326"),
        ("TIME", valid_at),
        ("VERSION", "2.0.1"),
        ("SUBSET", f"x({bounds.west},{bounds.east})"),
        ("SUBSET", f"y({bounds.south},{bounds.north})"),
        ("RESOLUTION", f"y({resolution_deg})"),
    ]
    response = _fetch_geomet(f"{GEOMET_URL}?{urlencode(query)}", stats)
    if response.status_code != 200:
        raise RuntimeError(f"GeoMet {layer} at {valid_at} failed with {response.status_code}")
    content_type = response.headers.get("content-type", "")
    if stats:
        stats.record_bytes(len(response.content))
    if "tiff" not in content_type.lower():
        raise coverage_error(layer, valid_at, content_type, response.text)
    return parse_geotiff_grid(response.content)


def coverage_error(layer: str, valid_at: str, content_type: str, body: str) -> RuntimeError:
    detail = re.sub(r"\s+", " ", body)[:240]
    message = f"GeoMet {layer} at {valid_at} returned {content_type}: {detail}"
    if re.search(r'code="NoMatch"[^>]*locator="time"', body):
        return CoverageUnavailableError(message)
    return RuntimeError(message)


def _fetch_geomet(url: str, stats: GeoMetRequestStats | None) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(3):
        if stats:
            stats.record_request(retry=attempt > 0)
        retry_delay_s: float | None = None
        try:
            response = _session().get(url, timeout=REQUEST_TIMEOUT_S)
            if response.status_code == 200 or (
                response.status_code != 429 and response.status_code < 500
            ):
                return response
            last_error = RuntimeError(f"GeoMet request failed with {response.status_code}")
            retry_delay_s = _retry_after_s(response)
        except requests.RequestException as error:
            last_error = error
        if attempt < 2:
            time.sleep(retry_delay_s if retry_delay_s is not None else _backoff_s(attempt))
    assert last_error is not None
    raise last_error


def _backoff_s(attempt: int) -> float:
    base = 0.25 * (2**attempt)
    return base * (0.75 + random.random() * 0.5)


def _retry_after_s(response: requests.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now().astimezone()).total_seconds()
        except (TypeError, ValueError):
            return None
    return min(MAX_RETRY_DELAY_S, max(0.25, seconds))


def _parses_as_instant(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False
