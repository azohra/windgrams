from pathlib import Path

import pytest

from windgrams.build_gfs import (
    _deaveraged,
    _differenced,
    _window_start,
)
from windgrams.moisture import dew_point_depression
from windgrams.noaa import find_record, parse_idx

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("forecast_hour", "start"),
    [(3, 0), (6, 0), (21, 18), (24, 18), (123, 120), (126, 120), (384, 378)],
)
def test_windows_reset_every_six_hours(forecast_hour, start):
    assert _window_start(forecast_hour) == start


def test_a_constant_flux_survives_deaveraging():
    # A(21) and A(24) both average a constant 130 W/m²; the (21, 24] mean is 130.
    assert _deaveraged(130.0, 130.0) == 130.0


def test_deaveraging_recovers_the_second_half_of_the_window():
    # 100 W/m² over (18, 21], 200 W/m² over (21, 24]: the 6 h average is 150.
    assert _deaveraged(150.0, 100.0) == 200.0


def test_differencing_recovers_the_second_half_of_an_accumulation():
    # 2 mm fell by f021, 5 mm by f024: 3 mm fell over (21, 24].
    assert _differenced(5.0, 2.0) == 3.0


def test_windowed_records_exist_under_their_exact_forecast_names():
    f021 = parse_idx((FIXTURES / "gfs.t12z.pgrb2.0p25.f021.excerpt.idx").read_text())
    f024 = parse_idx((FIXTURES / "gfs.t12z.pgrb2.0p25.f024.excerpt.idx").read_text())

    for records, window in ((f021, "18-21"), (f024, "18-24")):
        find_record(records, "LHTFL", "surface", f"{window} hour ave fcst")
        find_record(records, "SHTFL", "surface", f"{window} hour ave fcst")
        find_record(records, "APCP", "surface", f"{window} hour acc fcst")


def test_inverse_magnus_matches_hand_checked_dewpoints():
    # 20 °C at 50 % RH dews at 9.26 °C; 5 °C at 80 % RH dews at 1.84 °C.
    assert dew_point_depression(20.0, 50.0) == pytest.approx(20.0 - 9.26, abs=0.01)
    assert dew_point_depression(5.0, 80.0) == pytest.approx(5.0 - 1.84, abs=0.01)


def test_saturated_air_has_no_depression():
    assert dew_point_depression(15.0, 100.0) == pytest.approx(0.0, abs=1e-9)


def test_relative_humidity_is_clamped_to_a_physical_range():
    assert dew_point_depression(20.0, 0.0) == dew_point_depression(20.0, 1.0)
    assert dew_point_depression(20.0, 105.0) == dew_point_depression(20.0, 100.0)
