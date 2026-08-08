from pathlib import Path

import pytest

from windgrams.noaa import byte_range, find_record, parse_idx, sample_sites, wind_from_uv

FIXTURES = Path(__file__).parent / "fixtures"


def hrrr_records():
    return parse_idx((FIXTURES / "hrrr.t12z.wrfprsf24.excerpt.idx").read_text())


def gfs_records():
    return parse_idx((FIXTURES / "gfs.t12z.pgrb2.0p25.f024.excerpt.idx").read_text())


def test_parses_idx_lines_into_offsets_and_lengths():
    records = hrrr_records()

    assert records[0].variable == "HGT"
    assert records[0].level == "850 mb"
    assert records[0].forecast == "24 hour fcst"
    assert records[0].offset == 216059484
    # A record's length is the next record's offset minus its own.
    assert records[0].length == records[1].offset - records[0].offset == 718591


def test_the_last_record_reads_to_end_of_file():
    records = hrrr_records()

    assert records[-1].length is None
    assert byte_range(records[-1]) == f"bytes={records[-1].offset}-"


def test_byte_range_is_inclusive():
    records = hrrr_records()

    assert byte_range(records[0]) == "bytes=216059484-216778074"


def test_finds_a_record_by_variable_level_and_forecast():
    record = find_record(hrrr_records(), "TMP", "850 mb", "24 hour fcst")

    assert record.offset == 216778075


def test_forecast_field_separates_instantaneous_from_averaged_cloud_cover():
    records = gfs_records()

    instantaneous = find_record(records, "TCDC", "entire atmosphere", "24 hour fcst")
    averaged = find_record(records, "TCDC", "entire atmosphere", "18-24 hour ave fcst")

    assert instantaneous.offset != averaged.offset


def test_forecast_field_separates_windowed_from_run_total_accumulations():
    records = gfs_records()

    windowed = find_record(records, "APCP", "surface", "18-24 hour acc fcst")
    run_total = find_record(records, "APCP", "surface", "0-1 day acc fcst")

    assert windowed.offset != run_total.offset


def test_a_missing_record_raises():
    with pytest.raises(RuntimeError, match="DPT:850 mb"):
        find_record(gfs_records(), "DPT", "850 mb", "24 hour fcst")


@pytest.mark.parametrize(
    ("u", "v", "speed", "direction"),
    [
        (0, -5, 5, 0),  # northerly: blowing toward the south comes FROM the north
        (-5, 0, 5, 90),  # easterly
        (0, 5, 5, 180),  # southerly
        (5, 0, 5, 270),  # westerly
        (3, 4, 5, pytest.approx(216.87, abs=0.01)),
    ],
)
def test_wind_from_uv_uses_the_meteorological_from_convention(u, v, speed, direction):
    assert wind_from_uv(u, v) == (speed, direction)


def sample_message(values):
    import eccodes

    gid = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    try:
        # The sample is a 16x31 grid spanning 0-60N, 0-30E at 2-degree
        # spacing; values arrive in scanning order.
        eccodes.codes_set_values(gid, values)
        return eccodes.codes_get_message(gid)
    finally:
        eccodes.codes_release(gid)


def test_sample_sites_resolves_the_grid_index_once_per_grid(monkeypatch):
    import eccodes

    from windgrams import noaa

    monkeypatch.setattr(noaa, "_grid_points_cache", {})
    searches = []
    real_find_nearest = eccodes.codes_grib_find_nearest

    def counting_find_nearest(*args, **kwargs):
        searches.append(args)
        return real_find_nearest(*args, **kwargs)

    monkeypatch.setattr(eccodes, "codes_grib_find_nearest", counting_find_nearest)
    sites = [
        {"slug": "a", "name": "A", "latitude": 48.1, "longitude": 10.1},
        {"slug": "b", "name": "B", "latitude": 30.0, "longitude": 20.0},
    ]
    grid_size = 16 * 31

    first = sample_sites(sample_message([1.0] * grid_size), sites, max_distance_km=1000)
    second = sample_sites(sample_message([2.0] * grid_size), sites, max_distance_km=1000)

    assert {point.value for point in first.values()} == {1.0}
    assert {point.value for point in second.values()} == {2.0}
    # One nearest-neighbour search per site, ever — the second message hits
    # the cached grid indices.
    assert len(searches) == len(sites)
    assert first["a"].distance_km == second["a"].distance_km


def test_sample_sites_still_rejects_sites_far_from_any_gridpoint(monkeypatch):
    from windgrams import noaa

    monkeypatch.setattr(noaa, "_grid_points_cache", {})
    # In-domain, but ~100 km from the nearest gridpoint of the 2-degree grid.
    sites = [{"slug": "a", "name": "A", "latitude": 47.0, "longitude": 11.0}]

    with pytest.raises(RuntimeError, match="outside the model grid"):
        sample_sites(sample_message([1.0] * (16 * 31)), sites, max_distance_km=1)
