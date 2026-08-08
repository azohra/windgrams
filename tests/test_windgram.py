import math

import pytest

from windgrams.windgram import (
    WINDGRAM_MODEL,
    derive_windgram_profile,
    windgram_display_hours,
)


def source_profile() -> dict:
    return {
        "generatedAt": "2026-07-27T19:00:00.000Z",
        "modelElevationM": 1200,
        "referenceTime": "2026-07-27T18:00:00Z",
        "siteAltitudeM": 1485,
        "siteId": "dundee",
        "siteName": "Dundee",
        "hours": [
            {
                "cloudCoverPercent": 35,
                "dewPointDepressionC": 6,
                "latentHeatFluxWm2": 160,
                "precipitationMm": 0.2,
                "pressurePa": 101_200,
                "sensibleHeatFluxWm2": 320,
                "temperatureC": 24,
                "validAt": "2026-07-27T19:00:00Z",
                "windDirectionDeg": -20,
                "windSpeedMs": 5,
                "levels": [
                    {
                        "dewPointDepressionC": 5,
                        "heightM": 1500,
                        "pressureHpa": 850,
                        "temperatureC": 20,
                        "windDirectionDeg": 270,
                        "windSpeedMs": 6,
                    },
                    {
                        "dewPointDepressionC": 3,
                        "heightM": 2100,
                        "pressureHpa": 800,
                        "temperatureC": 14,
                        "windDirectionDeg": 280,
                        "windSpeedMs": 8,
                    },
                    {
                        "dewPointDepressionC": 0.4,
                        "heightM": 2700,
                        "pressureHpa": 750,
                        "temperatureC": 8,
                        "windDirectionDeg": 290,
                        "windSpeedMs": 10,
                    },
                ],
            }
        ],
    }


def test_converts_a_source_profile_into_pilot_facing_units_and_derived_heights():
    profile = derive_windgram_profile(source_profile())
    hour = profile["hours"][0]

    assert profile["model"] == WINDGRAM_MODEL
    assert hour["windDirectionDeg"] == 340
    assert hour["windSpeedKmh"] == 18
    assert hour["pressureKpa"] == pytest.approx(101.2)
    assert hour["cloudBaseM"] == 1926
    assert hour["boundaryLayerTopM"] > profile["modelElevationM"]
    assert hour["thermalVelocityMs"] > 0
    assert hour["levels"][0]["lapseCPer1000Ft"] == pytest.approx(-3.048)
    assert hour["levels"][2]["cloud"] is True


def test_does_not_claim_usable_lift_when_surface_heating_is_absent():
    source = source_profile()
    source["hours"][0]["sensibleHeatFluxWm2"] = -20
    source["hours"][0]["latentHeatFluxWm2"] = 0

    hour = derive_windgram_profile(source)["hours"][0]
    assert hour["thermalVelocityMs"] == 0
    assert hour["usableLiftTopM"] is None


def test_does_not_smooth_derived_heights_across_an_overnight_gap():
    source = source_profile()
    base = source["hours"][0]
    times = [
        "2026-07-27T14:00:00Z",
        "2026-07-27T15:00:00Z",
        "2026-07-27T16:00:00Z",
        "2026-07-28T14:00:00Z",
        "2026-07-28T15:00:00Z",
        "2026-07-28T16:00:00Z",
    ]
    depressions = [1, 1, 10, 0, 0, 0]
    source["hours"] = [
        {
            **base,
            "dewPointDepressionC": depression,
            "levels": [dict(level) for level in base["levels"]],
            "validAt": valid_at,
        }
        for valid_at, depression in zip(times, depressions)
    ]

    hours = derive_windgram_profile(source)["hours"]

    assert hours[2]["cloudBaseM"] == 2410
    assert hours[3]["cloudBaseM"] == 1200


@pytest.mark.parametrize(
    ("reference_time_ms", "expected_count", "first_hour", "last_hour"),
    [
        ("2026-07-27T00:00:00Z", 26, 14, 48),
        ("2026-07-27T06:00:00Z", 30, 8, 46),
        ("2026-07-27T12:00:00Z", 30, 2, 40),
        ("2026-07-27T18:00:00Z", 30, 1, 48),
    ],
)
def test_selects_only_complete_daylight_days(
    reference_time_ms, expected_count, first_hour, last_hour
):
    from datetime import datetime, timedelta

    reference = datetime.fromisoformat(reference_time_ms.replace("Z", "+00:00"))
    candidates = [
        {
            "forecastHour": hour,
            "validAt": (reference + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        for hour in range(1, 49)
    ]

    selected = windgram_display_hours(candidates)

    assert len(selected) == expected_count
    assert selected[0]["forecastHour"] == first_hour
    assert selected[-1]["forecastHour"] == last_hour


def test_a_lower_daily_minimum_keeps_three_hourly_days_with_one_missing_step():
    from datetime import datetime, timedelta

    # A GDPS-style day: 3-hourly steps put exactly five columns inside the
    # 07:00–21:00 Pacific window; drop one and the default minimum loses the
    # whole day while a minimum of four keeps the rest.
    reference = datetime.fromisoformat("2026-07-27T00:00:00+00:00")
    candidates = [
        {
            "forecastHour": hour,
            "validAt": (reference + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        for hour in range(3, 49, 3)
        if hour != 18  # 11:00 Pacific, inside the display window
    ]

    assert windgram_display_hours(candidates) == candidates
    selected = windgram_display_hours(candidates, min_hours_per_day=4)
    assert [hour["forecastHour"] for hour in selected] == [15, 21, 24, 27, 39, 42, 45, 48]


def test_normalizes_wind_directions_including_negatives():
    source = source_profile()
    source["hours"][0]["windDirectionDeg"] = -370
    hour = derive_windgram_profile(source)["hours"][0]
    assert hour["windDirectionDeg"] == 350
    assert math.isfinite(hour["windSpeedKmh"])
