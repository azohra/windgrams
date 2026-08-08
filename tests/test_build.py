import pytest

from windgrams.build import _precip_for_hour, _previous_scheduled_hour
from windgrams.geomet import GDPS


def test_differences_run_total_accumulations_between_scheduled_steps():
    accumulations = {
        0: {"dundee": 0.0},
        3: {"dundee": 1.2},
        6: {"dundee": 4.0},
    }

    assert _precip_for_hour(accumulations.get, GDPS.forecast_hours, 3) == {"dundee": 1.2}
    assert _precip_for_hour(accumulations.get, GDPS.forecast_hours, 6)["dundee"] == pytest.approx(
        2.8
    )


def test_clamps_resampling_noise_to_non_negative_precipitation():
    accumulations = {3: {"erie": 5.0}, 6: {"erie": 4.9}}
    assert _precip_for_hour(accumulations.get, GDPS.forecast_hours, 6) == {"erie": 0.0}


def test_first_scheduled_step_differences_against_the_run_start():
    assert _previous_scheduled_hour(GDPS.forecast_hours, 3) == 0
    assert _previous_scheduled_hour(GDPS.forecast_hours, 240) == 237
    assert _previous_scheduled_hour((1, 2, 3), 1) == 0
