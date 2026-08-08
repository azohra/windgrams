import math

import pytest

from windgrams.build_hrrr import _earth_wind, _grid_rotation_deg
from windgrams.noaa import wind_from_uv


def test_no_rotation_on_the_orientation_meridian():
    assert _grid_rotation_deg(262.5) == 0
    assert _earth_wind(3.0, 4.0, 262.5) == (3.0, 4.0)


def test_rotation_at_the_catalogued_sites_is_the_documented_bias():
    # −117.7°W is 242.3°E; sin(38.5°) × (242.3 − 262.5) ≈ −12.6°.
    assert _grid_rotation_deg(242.3) == pytest.approx(-12.575, abs=0.001)
    assert _grid_rotation_deg(-117.7) == pytest.approx(_grid_rotation_deg(242.3))


def test_rotation_preserves_speed_and_shifts_direction_by_the_local_angle():
    # A wind blowing along grid north at 242.3°E: grid north there points
    # 12.6° east of true north, so the wind comes FROM 180° − 12.6°.
    u_earth, v_earth = _earth_wind(0.0, 10.0, 242.3)
    speed, direction = wind_from_uv(u_earth, v_earth)

    assert speed == pytest.approx(10.0)
    assert direction == pytest.approx(180 + _grid_rotation_deg(242.3))


def test_rotation_matrix_is_orthogonal_for_an_arbitrary_wind():
    u_earth, v_earth = _earth_wind(-7.3, 2.1, 250.0)

    assert math.hypot(u_earth, v_earth) == pytest.approx(math.hypot(-7.3, 2.1))
