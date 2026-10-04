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


def test_ephemeris_resolution(tmp_path, monkeypatch):
    from dial_a_moon_wrapper import geometry

    calls = []
    monkeypatch.setattr(geometry, "_load", lambda d, f: calls.append((d, f)))
    monkeypatch.delenv("DIALAMOON_EPHEMERIS", raising=False)
    root = tmp_path / "data" / "dialamoon"
    root.mkdir(parents=True)

    geometry.load_ephemeris(root)  # nothing local: download into the cache
    (tmp_path / "data" / "de421.bsp").write_bytes(b"")
    geometry.load_ephemeris(root)  # reuse a copy next to the cache
    geometry.load_ephemeris(root, tmp_path / "mine" / "jpl.bsp")  # explicit file, used as-is
    monkeypatch.setenv("DIALAMOON_EPHEMERIS", str(tmp_path / "env.bsp"))
    geometry.load_ephemeris(root)

    assert calls == [
        (str(root), "de421.bsp"),
        (str(tmp_path / "data"), "de421.bsp"),
        (str((tmp_path / "mine").resolve()), "jpl.bsp"),
        (str(tmp_path.resolve()), "env.bsp"),
    ]


@pytest.mark.ephemeris
def test_de421_range(ephemeris_root):
    from dial_a_moon_wrapper.geometry import check_date_supported, ephemeris_range

    first, last = ephemeris_range(ephemeris_root)
    assert first.date().isoformat() == "1899-07-29" or first.date().isoformat() == "1899-07-30"
    assert last.date().isoformat() in ("2053-10-07", "2053-10-08")

    check_date_supported(datetime(1900, 1, 1, tzinfo=timezone.utc), ephemeris_root)
    check_date_supported(datetime(2053, 1, 1, tzinfo=timezone.utc), ephemeris_root)
    for bad in (datetime(1899, 7, 1, tzinfo=timezone.utc), datetime(2060, 1, 1, tzinfo=timezone.utc)):
        with pytest.raises(ValueError, match="outside the DE421 ephemeris range"):
            check_date_supported(bad, ephemeris_root)
