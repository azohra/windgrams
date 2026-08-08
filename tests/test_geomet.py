from pathlib import Path

import pytest

from windgrams.geomet import (
    GDPS,
    HRDPS,
    RDPS,
    CoverageUnavailableError,
    coverage_error,
    parse_latest_reference_time,
    pressure_layer,
)


def test_reads_the_advertised_default_model_run():
    xml = """
      <Layer>
        <Dimension name="time" default="2026-07-27T17:00:00Z">...</Dimension>
        <Dimension name="reference_time" units="ISO8601"
          default="2026-07-27T12:00:00Z">...</Dimension>
      </Layer>
    """
    assert parse_latest_reference_time(xml) == "2026-07-27T12:00:00Z"


def test_fails_clearly_when_the_model_run_is_absent():
    with pytest.raises(RuntimeError, match="GeoMet did not advertise a current HRDPS run"):
        parse_latest_reference_time("<Layer />")


def test_builds_pressure_level_coverage_names():
    assert pressure_layer("windSpeedMs", 850) == "HRDPS.CONTINENTAL.PRES_WSPD.850"


def test_builds_new_style_pressure_level_coverage_names():
    assert RDPS.pressure_layer("temperatureC", 850) == "RDPS_10km_AirTemp_850mb"
    assert RDPS.pressure_layer("heightM", 600) == "RDPS_10km_GeopotentialHeight_600mb"
    assert GDPS.pressure_layer("windSpeedMs", 925) == "GDPS_15km_WindSpeed_925mb"


def test_hrdps_config_keeps_the_baseline_grid_schedule_and_output():
    assert HRDPS.pressure_layer("windSpeedMs", 850) == "HRDPS.CONTINENTAL.PRES_WSPD.850"
    assert HRDPS.resolution_deg == 0.0225
    assert HRDPS.forecast_hours == tuple(range(1, 49))
    assert HRDPS.out_dir == Path("data/hrdps-2p5km")
    assert HRDPS.min_hours_per_day == 5
    assert HRDPS.precip_accumulation_layer is None


def test_model_schedules_cover_their_advertised_horizons():
    assert RDPS.forecast_hours == tuple(range(1, 85))
    assert GDPS.forecast_hours == tuple(range(3, 241, 3))


def test_models_sample_at_the_fine_resolution_that_pins_native_cells():
    # GeoMet stretches any requested RESOLUTION to fit the subset; a fine
    # grid is what keeps nearest-cell sampling on the model's own cells.
    assert RDPS.resolution_deg == 0.0225
    assert GDPS.resolution_deg == 0.0225


def test_recognizes_a_missing_valid_time_as_coverage_unavailable():
    body = """<ogc:ServiceExceptionReport version="1.3.0">
      <ogc:ServiceException code="NoMatch" locator="time">Date et heure
      invalides / Invalid date and time</ogc:ServiceException>
    </ogc:ServiceExceptionReport>"""
    error = coverage_error("GDPS_15km_AirTemp_900mb", "2026-08-17T03:00:00Z", "text/xml", body)
    assert isinstance(error, CoverageUnavailableError)


def test_other_service_exceptions_stay_fatal():
    body = '<ogc:ServiceException code="LayerNotDefined">no</ogc:ServiceException>'
    error = coverage_error("HRDPS.CONTINENTAL_TT", "2026-08-08T00:00:00Z", "text/xml", body)
    assert not isinstance(error, CoverageUnavailableError)
    assert isinstance(error, RuntimeError)
