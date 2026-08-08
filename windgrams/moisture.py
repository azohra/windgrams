"""Moisture derivations shared by builders whose models publish no dew point
in any form (GFS pressure levels, every REPS member field)."""

from __future__ import annotations

import math


def dew_point_depression(temperature_c: float, rh_percent: float) -> float:
    """Inverse Magnus dew point depression from temperature and relative
    humidity, with humidity clamped to a physical range."""
    rh = min(100.0, max(1.0, rh_percent))
    gamma = math.log(rh / 100) + (17.625 * temperature_c) / (243.04 + temperature_c)
    dew_point_c = 243.04 * gamma / (17.625 - gamma)
    return temperature_c - dew_point_c
