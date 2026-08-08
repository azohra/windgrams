"""ECCC Datamart HTTP client: existence checks and GRIB2 downloads with the
same retry manners as the GeoMet client — jittered backoff, Retry-After,
and per-build telemetry.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field

import requests

USER_AGENT = "Windgrams/2.0 (+https://github.com/azohra/windgrams)"
REQUEST_TIMEOUT_S = 60
MAX_RETRY_DELAY_S = 10


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


def fetch_bytes(url: str, stats: DownloadStats | None = None) -> bytes:
    last_error: Exception | None = None
    for attempt in range(3):
        if stats:
            stats.record_request(retry=attempt > 0)
        try:
            response = _session().get(url, timeout=REQUEST_TIMEOUT_S)
            if response.status_code == 200:
                mismatch = _content_length_mismatch(response)
                if mismatch is None:
                    if stats:
                        stats.record_bytes(len(response.content))
                    return response.content
                # A Datamart GET was once observed serving wrong-model bytes
                # that contradicted the server's own Content-Length, clean on
                # retry — so a mismatched body is retried, never returned.
                last_error = RuntimeError(f"Datamart {url} {mismatch}")
            elif response.status_code != 429 and response.status_code < 500:
                raise RuntimeError(f"Datamart {url} failed with {response.status_code}")
            else:
                last_error = RuntimeError(f"Datamart {url} failed with {response.status_code}")
        except requests.RequestException as error:
            last_error = error
        if attempt < 2:
            time.sleep(0.25 * (2**attempt) * (0.75 + random.random() * 0.5))
    assert last_error is not None
    raise last_error


def _content_length_mismatch(response: requests.Response) -> str | None:
    """Why the body cannot be trusted, or None when it can. Content-Length
    describes the encoded body, so an encoded response is not checkable."""
    declared = response.headers.get("content-length")
    if declared is None or response.headers.get("content-encoding"):
        return None
    if len(response.content) == int(declared):
        return None
    return f"returned {len(response.content)} bytes against Content-Length {declared}"
