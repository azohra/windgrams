import gzip
import json
import os

from pathlib import Path

from windgrams.publish import append_history


def test_appends_one_readable_json_line_per_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    profile = {"siteId": "dundee", "referenceTime": "2026-08-07T12:00:00Z", "hours": []}

    append_history(profile, Path("data/hrdps-2p5km/history"))
    append_history({**profile, "referenceTime": "2026-08-07T18:00:00Z"}, Path("data/hrdps-2p5km/history"))

    archive = tmp_path / "data/hrdps-2p5km/history/dundee/2026.jsonl.gz"
    with gzip.open(archive, "rt") as handle:
        runs = [json.loads(line) for line in handle]
    assert [run["referenceTime"] for run in runs] == [
        "2026-08-07T12:00:00Z",
        "2026-08-07T18:00:00Z",
    ]


def test_rotates_archives_by_reference_year(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    append_history({"siteId": "erie", "referenceTime": "2026-12-31T18:00:00Z"}, Path("data/hrdps-2p5km/history"))
    append_history({"siteId": "erie", "referenceTime": "2027-01-01T00:00:00Z"}, Path("data/hrdps-2p5km/history"))

    assert sorted(os.listdir(tmp_path / "data/hrdps-2p5km/history/erie")) == [
        "2026.jsonl.gz",
        "2027.jsonl.gz",
    ]
