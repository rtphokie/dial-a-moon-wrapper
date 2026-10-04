from datetime import datetime, timezone

import pytest

from dial_a_moon_wrapper.catalog import parse_nasa_time
from dial_a_moon_wrapper.geometry import (
    compute_observer_geometry,
    compute_target_geometry,
    parallactic_angle,
)


def wrap(d):
    return (d + 180.0) % 360.0 - 180.0


def test_parallactic_angle_on_meridian_north():
    assert parallactic_angle(0.0, 0.0, 35.0) == pytest.approx(0.0)


def test_parallactic_angle_on_meridian_south_hemisphere():
    # Southern observer looking north at the Moon: zenith is "down" in a
    # north-up image.
    assert abs(parallactic_angle(0.0, 0.0, -34.0)) == pytest.approx(180.0)


def test_parallactic_angle_sign_east_west():
    assert parallactic_angle(-60.0, 10.0, 35.0) < 0  # rising, east
    assert parallactic_angle(60.0, 10.0, 35.0) > 0  # setting, west


@pytest.mark.ephemeris
def test_target_geometry_matches_nasa(reference_records, ephemeris_root):
    """Locally computed geometry agrees with NASA's published values."""

    for item in reference_records:
        t = parse_nasa_time(item["time"])
        g = compute_target_geometry(t, ephemeris_root)
        assert wrap(g.subearth_lon - item["subearth"]["lon"]) == pytest.approx(0, abs=0.1)
        assert g.subearth_lat == pytest.approx(item["subearth"]["lat"], abs=0.1)
        assert wrap(g.subsolar_lon - item["subsolar"]["lon"]) == pytest.approx(0, abs=0.1)
        assert g.subsolar_lat == pytest.approx(item["subsolar"]["lat"], abs=0.1)
        assert g.distance == pytest.approx(item["distance"], abs=2.0)
        assert wrap(g.posangle - item["posangle"]) == pytest.approx(0, abs=0.3)


@pytest.mark.ephemeris
def test_observer_geometry_is_plain_floats(ephemeris_root):
    o = compute_observer_geometry(
        datetime(2026, 10, 5, 2, tzinfo=timezone.utc), 35.78, -78.64, 100.0, ephemeris_root
    )
    assert all(type(v) is float for v in (o.altitude, o.azimuth, o.parallactic_angle))
    assert -90 <= o.altitude <= 90 and 0 <= o.azimuth < 360
