import math

import pytest

from windgrams.build_reps import (
    MEMBER_COUNT,
    PERTURBATION_NUMBERS,
    _aggregate_hours,
    _forecast_hours,
    member_layer,
    percentile,
)
from windgrams.grib import earth_wind, split_messages
from windgrams.moisture import dew_point_depression
from windgrams.publish import compact_json

REPS_SOUTH_POLE = (-25.64728, 269.555534)
DUNDEE = (49.291977, -117.183569)


# --- percentiles -----------------------------------------------------------


def test_the_published_points_land_on_exact_ranks_for_21_members():
    values = sorted(float(v) for v in range(21))

    assert percentile(values, 10) == 2
    assert percentile(values, 25) == 5
    assert percentile(values, 50) == 10
    assert percentile(values, 75) == 15
    assert percentile(values, 90) == 18


def test_percentiles_interpolate_linearly_between_ranks():
    # rank = 3 × 25/100 = 0.75, between 1 and 2.
    assert percentile([1.0, 2.0, 3.0, 4.0], 25) == 1.75


def test_ties_collapse_to_the_tied_value():
    assert percentile([5.0, 5.0, 5.0, 5.0, 9.0], 50) == 5.0


def test_a_single_value_is_every_percentile():
    for point in (10, 25, 50, 75, 90):
        assert percentile([7.5], point) == 7.5


def test_percentile_of_nothing_raises():
    with pytest.raises(ValueError):
        percentile([], 50)


# --- member pairing --------------------------------------------------------


def test_geomet_suffix_01_is_the_grib_control_member():
    # GeoMet's .01 is labelled "[control member]" in its capabilities; GRIB2
    # encodes the control as perturbationNumber 0.
    assert member_layer("REPS.MEM.ETA_FC", 0) == "REPS.MEM.ETA_FC.01"


def test_geomet_suffixes_run_01_to_21_across_the_ensemble():
    layers = [member_layer("REPS.MEM.ETA_TT", member) for member in PERTURBATION_NUMBERS]

    assert len(layers) == len(set(layers)) == MEMBER_COUNT == 21
    assert layers[0].endswith(".01")
    assert layers[-1].endswith(".21")


# --- dew point depression (shared moisture module) ---------------------------


def test_dew_point_depression_matches_the_gfs_reference_values():
    assert dew_point_depression(20.0, 50.0) == pytest.approx(20.0 - 9.26, abs=0.01)
    assert dew_point_depression(15.0, 100.0) == pytest.approx(0.0, abs=1e-9)


# --- wind rotation ---------------------------------------------------------


def test_an_unrotated_grid_leaves_the_wind_alone():
    # A south pole at the true south pole is the identity rotation.
    east, north = earth_wind(3.0, 4.0, 49.3, -117.2, -90.0, 0.0)

    assert east == pytest.approx(3.0, abs=1e-12)
    assert north == pytest.approx(4.0, abs=1e-12)


def test_an_equatorial_pole_turns_the_wind_a_quarter_circle():
    # South pole of rotation on the equator at 0°E puts the rotated north
    # pole at (0°, 180°). At the geographic point (0°, 90°E) grid-north
    # points toward (0°, 180°) — due true east — and grid-east points at the
    # rotated south pole — due true south.
    east, north = earth_wind(1.0, 0.0, 0.0, 90.0, 0.0, 0.0)
    assert (east, north) == (pytest.approx(0.0, abs=1e-12), pytest.approx(-1.0, abs=1e-12))

    east, north = earth_wind(0.0, 1.0, 0.0, 90.0, 0.0, 0.0)
    assert (east, north) == (pytest.approx(1.0, abs=1e-12), pytest.approx(0.0, abs=1e-12))


def test_rotation_conserves_wind_speed_on_the_reps_grid():
    east, north = earth_wind(3.0, -4.0, *DUNDEE, *REPS_SOUTH_POLE)

    assert math.hypot(east, north) == pytest.approx(5.0, abs=1e-12)


def test_grid_north_points_along_the_bearing_to_the_rotated_pole():
    # Independent geometry: grid-north lies on the rotated meridian, so a
    # pure grid-north wind must point along the great-circle initial bearing
    # from the site to the rotated north pole.
    pole_latitude, pole_longitude = -REPS_SOUTH_POLE[0], REPS_SOUTH_POLE[1] - 180.0
    lat1, lon1 = map(math.radians, DUNDEE)
    lat2, lon2 = math.radians(pole_latitude), math.radians(pole_longitude)
    bearing = math.degrees(
        math.atan2(
            math.sin(lon2 - lon1) * math.cos(lat2),
            math.cos(lat1) * math.sin(lat2)
            - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1),
        )
    ) % 360

    east, north = earth_wind(0.0, 1.0, *DUNDEE, *REPS_SOUTH_POLE)
    points_toward = math.degrees(math.atan2(east, north)) % 360

    assert points_toward == pytest.approx(bearing, abs=1e-9)


# --- GRIB message splitting -------------------------------------------------


def fake_message(payload: bytes) -> bytes:
    body = b"\x00\x00\x02\x02" + payload + b"7777"
    length = 4 + 4 + 8 + len(body)
    return b"GRIB" + b"\x00\x00\x02\x02" + length.to_bytes(8, "big") + body


def test_split_messages_returns_each_stacked_member():
    first, second = fake_message(b"member zero"), fake_message(b"one")

    assert split_messages(first + second) == [first, second]


def test_misaligned_bytes_fail_loudly():
    with pytest.raises(ValueError, match="misaligned"):
        split_messages(b"JUNK" + fake_message(b"x"))


def test_a_truncated_message_fails_loudly():
    with pytest.raises(ValueError, match="truncated"):
        split_messages(fake_message(b"x")[:-2])


# --- step subsets ------------------------------------------------------------


def test_explicit_steps_must_be_on_the_three_hourly_schedule():
    assert _forecast_hours("24,18,21") == (18, 21, 24)
    with pytest.raises(RuntimeError, match="17"):
        _forecast_hours("17")


# --- aggregation and serialization ------------------------------------------


def member_hour(**overrides) -> dict:
    hour = {
        "boundaryLayerTopM": 1500.0,
        "cloudBaseM": 2400.0,
        "cloudCoverPercent": 20.0,
        "precipitationMm": 0.0,
        "pressureKpa": 101.0,
        "surfaceTemperatureC": 20.0,
        "thermalVelocityMs": 2.0,
        "usableLiftTopM": None,
        "validAt": "2026-08-07T21:00:00Z",
        "windDirectionDeg": 265.0,
        "windSpeedKmh": 10.0,
        "levels": [{"heightM": 1521.0}, {"heightM": 5720.0}],
    }
    hour.update(overrides)
    return hour


def test_null_members_stay_out_of_the_ranking_but_are_counted():
    profiles = [
        {"hours": [member_hour(usableLiftTopM=None)]},
        {"hours": [member_hour(usableLiftTopM=2200.0)]},
    ]

    (hour,) = _aggregate_hours(profiles)

    assert hour["usableLiftTopM"]["members"] == 1
    assert hour["usableLiftTopM"]["p50"] == 2200.0
    assert hour["boundaryLayerTopM"]["members"] == 2


def test_all_null_scalars_publish_null_percentiles():
    profiles = [
        {"hours": [member_hour(boundaryLayerTopM=None, usableLiftTopM=None)]},
        {"hours": [member_hour(boundaryLayerTopM=None, usableLiftTopM=None)]},
    ]

    (hour,) = _aggregate_hours(profiles)

    assert hour["boundaryLayerTopM"] == {
        "ceiledMembers": 0,
        "members": 0,
        "p10": None,
        "p25": None,
        "p50": None,
        "p75": None,
        "p90": None,
    }


def test_wind_direction_is_not_aggregated():
    profiles = [{"hours": [member_hour()]}, {"hours": [member_hour()]}]

    (hour,) = _aggregate_hours(profiles)

    assert "windDirectionDeg" not in hour


# --- ceiling censoring --------------------------------------------------------


def test_fully_ceiled_hours_count_every_member_and_keep_percentiles():
    # Both members clamped at the top of their own column — the percentiles
    # survive as lower bounds and ceiledMembers says they are censored.
    profiles = [
        {"hours": [member_hour(boundaryLayerTopM=5720.0)]},
        {"hours": [member_hour(boundaryLayerTopM=5740.0, levels=[{"heightM": 5740.0}])]},
    ]

    (hour,) = _aggregate_hours(profiles)

    assert hour["boundaryLayerTopM"]["ceiledMembers"] == 2
    assert hour["boundaryLayerTopM"]["members"] == 2
    assert hour["boundaryLayerTopM"]["p50"] == 5730.0


def test_partially_ceiled_hours_count_only_the_clamped_members():
    profiles = [
        {"hours": [member_hour(usableLiftTopM=5720.0)]},  # at its column top
        {"hours": [member_hour(usableLiftTopM=3400.0)]},  # measured below it
        {"hours": [member_hour(usableLiftTopM=None)]},  # no lift: in neither count
    ]

    (hour,) = _aggregate_hours(profiles)

    assert hour["usableLiftTopM"]["ceiledMembers"] == 1
    assert hour["usableLiftTopM"]["members"] == 2


def test_uncensored_hours_publish_zero_ceiled_members():
    profiles = [
        {"hours": [member_hour(boundaryLayerTopM=2100.0, usableLiftTopM=2500.0)]},
        {"hours": [member_hour(boundaryLayerTopM=2300.0, usableLiftTopM=2900.0)]},
    ]

    (hour,) = _aggregate_hours(profiles)

    assert hour["boundaryLayerTopM"]["ceiledMembers"] == 0
    assert hour["usableLiftTopM"]["ceiledMembers"] == 0


def test_the_ceiling_check_tolerates_the_float_round_trip():
    profiles = [
        {"hours": [member_hour(boundaryLayerTopM=5720.0 - 0.4)]},  # clamped, re-added
        {"hours": [member_hour(boundaryLayerTopM=5720.0 - 0.6)]},  # genuinely below
    ]

    (hour,) = _aggregate_hours(profiles)

    assert hour["boundaryLayerTopM"]["ceiledMembers"] == 1


def test_only_column_limited_scalars_carry_a_ceiled_count():
    profiles = [{"hours": [member_hour()]}, {"hours": [member_hour()]}]

    (hour,) = _aggregate_hours(profiles)

    assert "ceiledMembers" in hour["boundaryLayerTopM"]
    assert "ceiledMembers" in hour["usableLiftTopM"]
    assert "ceiledMembers" not in hour["cloudBaseM"]
    assert "ceiledMembers" not in hour["thermalVelocityMs"]


def test_a_small_document_serializes_deterministically():
    profiles = [
        {"hours": [member_hour()]},
        {
            "hours": [
                member_hour(
                    boundaryLayerTopM=2500.0,
                    cloudBaseM=2600.0,
                    cloudCoverPercent=40.0,
                    precipitationMm=1.0,
                    pressureKpa=102.0,
                    surfaceTemperatureC=22.5,
                    thermalVelocityMs=3.0,
                    usableLiftTopM=2200.0,
                    windSpeedKmh=20.0,
                )
            ]
        },
    ]
    document = {
        "generatedAt": "2026-08-07T22:00:00.000Z",
        "memberCount": 2,
        "model": "REPS 10 km",
        "modelElevationM": 1200.0,
        "referenceTime": "2026-08-07T12:00:00Z",
        "siteAltitudeM": 1485,
        "siteId": "dundee",
        "siteName": "Dundee",
        "hours": _aggregate_hours(profiles),
    }

    assert compact_json(document) == (
        '{"generatedAt":"2026-08-07T22:00:00.000Z","memberCount":2,'
        '"model":"REPS 10 km","modelElevationM":1200,'
        '"referenceTime":"2026-08-07T12:00:00Z",'
        '"siteAltitudeM":1485,"siteId":"dundee","siteName":"Dundee","hours":['
        '{"boundaryLayerTopM":{"ceiledMembers":0,"members":2,"p10":1600,"p25":1750,"p50":2000,"p75":2250,"p90":2400},'
        '"cloudBaseM":{"members":2,"p10":2420,"p25":2450,"p50":2500,"p75":2550,"p90":2580},'
        '"cloudCoverPercent":{"members":2,"p10":22,"p25":25,"p50":30,"p75":35,"p90":38},'
        '"precipitationMm":{"members":2,"p10":0.1,"p25":0.25,"p50":0.5,"p75":0.75,"p90":0.9},'
        '"pressureKpa":{"members":2,"p10":101.1,"p25":101.25,"p50":101.5,"p75":101.75,"p90":101.9},'
        '"surfaceTemperatureC":{"members":2,"p10":20.25,"p25":20.625,"p50":21.25,"p75":21.875,"p90":22.25},'
        '"thermalVelocityMs":{"members":2,"p10":2.1,"p25":2.25,"p50":2.5,"p75":2.75,"p90":2.9},'
        '"usableLiftTopM":{"ceiledMembers":0,"members":1,"p10":2200,"p25":2200,"p50":2200,"p75":2200,"p90":2200},'
        '"validAt":"2026-08-07T21:00:00Z",'
        '"windSpeedKmh":{"members":2,"p10":11,"p25":12.5,"p50":15,"p75":17.5,"p90":19}}]}'
    )
