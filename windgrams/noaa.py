"""NOAA Open Data GRIB2 access shared by the HRRR and GFS builders.

NOAA's public S3 buckets publish whole-domain GRIB2 files with NOMADS-style
.idx sidecars — one line per record, "n:byteOffset:d=YYYYMMDDHH:VAR:level:
ftime:". A record's length is the next record's offset minus its own; the
last record runs to end of file. One record is therefore one HTTP Range
request, so a build downloads megabytes of the fields it needs instead of
multi-hundred-megabyte files. Retry manners mirror datamart.py: a Session
per thread, jittered backoff, and per-build telemetry for the manifests.
"""

from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass, field

import eccodes
import requests

USER_AGENT = "Windgrams/2.0 (+https://github.com/azohra/windgrams)"
REQUEST_TIMEOUT_S = 60


@dataclass(frozen=True)
class IdxRecord:
    variable: str
    level: str
    forecast: str
    offset: int
    length: int | None  # None: the file's last record, read to end of file.


def parse_idx(text: str) -> list[IdxRecord]:
    rows = []
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) < 6:
            continue
        rows.append((int(parts[1]), parts[3], parts[4], parts[5]))

    records = []
    for index, (offset, variable, level, forecast) in enumerate(rows):
        length = rows[index + 1][0] - offset if index + 1 < len(rows) else None
        records.append(IdxRecord(variable, level, forecast, offset, length))
    return records


def find_record(records: list[IdxRecord], variable: str, level: str, forecast: str) -> IdxRecord:
    for record in records:
        if record.variable == variable and record.level == level and record.forecast == forecast:
            return record
    raise RuntimeError(f"{variable}:{level}:{forecast} is not in the GRIB index")


def byte_range(record: IdxRecord) -> str:
    if record.length is None:
        return f"bytes={record.offset}-"
    return f"bytes={record.offset}-{record.offset + record.length - 1}"


@dataclass
class DownloadStats:
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


_session_local = threading.local()


def _session() -> requests.Session:
    session = getattr(_session_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
        _session_local.session = session
    return session


def exists(url: str) -> bool:
    response = _session().head(url, timeout=REQUEST_TIMEOUT_S)
    return response.status_code == 200


def fetch_index(url: str, stats: DownloadStats | None = None) -> list[IdxRecord]:
    return parse_idx(_get(url, stats).decode())


def fetch_record(url: str, record: IdxRecord, stats: DownloadStats | None = None) -> bytes:
    return _get(url, stats, headers={"Range": byte_range(record)})


def _get(url: str, stats: DownloadStats | None, headers: dict | None = None) -> bytes:
    last_error: Exception | None = None
    for attempt in range(3):
        if stats:
            stats.record_request(retry=attempt > 0)
        try:
            response = _session().get(url, headers=headers, timeout=REQUEST_TIMEOUT_S)
            if response.status_code in (200, 206):
                if stats:
                    stats.record_bytes(len(response.content))
                return response.content
            if response.status_code != 429 and response.status_code < 500:
                raise RuntimeError(f"NOAA {url} failed with {response.status_code}")
            last_error = RuntimeError(f"NOAA {url} failed with {response.status_code}")
        except requests.RequestException as error:
            last_error = error
        if attempt < 2:
            time.sleep(0.25 * (2**attempt) * (0.75 + random.random() * 0.5))
    assert last_error is not None
    raise last_error


@dataclass(frozen=True)
class GridPointValue:
    value: float | None
    latitude: float
    longitude: float
    distance_km: float


@dataclass(frozen=True)
class _GridPoint:
    index: int
    latitude: float
    longitude: float
    distance_km: float


# ecCodes has no fast nearest-neighbour path for Lambert (HRRR) or rotated
# grids: every codes_grib_find_nearest call scans the full grid (~0.2 s on
# HRRR's 1.9M points), which once multiplied by records × sites dominated a
# build. Every record in a run shares one grid, so the site→index mapping is
# resolved once per grid (keyed on ecCodes' hash of the grid definition
# section) and each record afterwards is a direct element read.
_grid_points_cache: dict[tuple, dict[str, _GridPoint]] = {}
_grid_points_lock = threading.Lock()


def _grid_points(gid, sites: list[dict], max_distance_km: float) -> dict[str, _GridPoint]:
    key = (
        eccodes.codes_get(gid, "md5GridSection"),
        max_distance_km,
        tuple((site["slug"], site["latitude"], site["longitude"]) for site in sites),
    )
    with _grid_points_lock:
        cached = _grid_points_cache.get(key)
    if cached is not None:
        return cached
    points = {}
    for site in sites:
        nearest = eccodes.codes_grib_find_nearest(gid, site["latitude"], site["longitude"])[0]
        if nearest.distance > max_distance_km:
            raise RuntimeError(
                f"{site['name']} is outside the model grid "
                f"(nearest gridpoint {nearest.distance:.0f} km away)"
            )
        points[site["slug"]] = _GridPoint(
            int(nearest.index), float(nearest.lat), float(nearest.lon), float(nearest.distance)
        )
    with _grid_points_lock:
        _grid_points_cache[key] = points
    return points


def sample_sites(
    message: bytes, sites: list[dict], max_distance_km: float
) -> dict[str, GridPointValue]:
    """Nearest-gridpoint values for every site, keyed by slug.

    ecCodes clamps out-of-domain points to the grid boundary and reports a
    huge distance, so a distance cap is what tells "nearest gridpoint" apart
    from "site is outside the model's domain".
    """
    gid = eccodes.codes_new_from_message(message)
    try:
        points = _grid_points(gid, sites, max_distance_km)
        missing = eccodes.codes_get(gid, "missingValue")
        samples = {}
        for site in sites:
            point = points[site["slug"]]
            value = eccodes.codes_get_double_element(gid, "values", point.index)
            samples[site["slug"]] = GridPointValue(
                None if value == missing else float(value),
                point.latitude,
                point.longitude,
                point.distance_km,
            )
        return samples
    finally:
        eccodes.codes_release(gid)


def wind_from_uv(u_ms: float, v_ms: float) -> tuple[float, float]:
    """Speed and meteorological FROM-north direction of an earth-relative wind,
    matching the convention of ECCC's WDIR layers used by the other builds."""
    speed = math.hypot(u_ms, v_ms)
    direction = math.degrees(math.atan2(-u_ms, -v_ms)) % 360
    return speed, direction
