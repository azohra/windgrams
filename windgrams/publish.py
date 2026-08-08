"""Shared output writing: profile JSON, manifests, and gzipped run history."""

from __future__ import annotations

import gzip
import json
from pathlib import Path


def append_history(profile: dict, history_dir: Path) -> None:
    """Archives the profile under <history_dir>/<slug>/<year>.jsonl.gz.

    Each run is appended as an independent gzip member, so existing bytes are
    never rewritten and any gzip reader sees one JSON line per model run.
    """
    year = profile["referenceTime"][:4]
    directory = history_dir / profile["siteId"]
    directory.mkdir(parents=True, exist_ok=True)
    line = compact_json(profile) + "\n"
    with (directory / f"{year}.jsonl.gz").open("ab") as archive:
        archive.write(gzip.compress(line.encode()))


def compact_json(value: dict) -> str:
    return json.dumps(_integral_floats_to_ints(value), allow_nan=False, separators=(",", ":"))


def write_json(path: Path, value: dict, *, compact: bool) -> None:
    if compact:
        text = compact_json(value)
    else:
        text = json.dumps(_integral_floats_to_ints(value), allow_nan=False, indent=2)
    path.write_text(text + "\n")


def _integral_floats_to_ints(value):
    """Matches the original serialisation: JavaScript prints 5.0 as 5."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        return int(value)
    if isinstance(value, list):
        return [_integral_floats_to_ints(item) for item in value]
    if isinstance(value, dict):
        return {key: _integral_floats_to_ints(item) for key, item in value.items()}
    return value
