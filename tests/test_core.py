import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from PIL import Image

from dial_a_moon_wrapper import core
from dial_a_moon_wrapper.catalog import Catalog
from dial_a_moon_wrapper.geometry import ObserverGeometry, TargetGeometry

UTC = timezone.utc


# --- time handling -------------------------------------------------------


def test_parse_local_datetime_dst():
    local, utc = core.parse_local_datetime("2026-07-04 21:30", "America/New_York")
    assert local.utcoffset().total_seconds() == -4 * 3600
    assert utc == datetime(2026, 7, 5, 1, 30, tzinfo=UTC)

    _, utc = core.parse_local_datetime("2026-01-04 21:30", "America/New_York")
    assert utc == datetime(2026, 1, 5, 2, 30, tzinfo=UTC)


def test_parse_local_datetime_iso_with_offset_is_respected():
    local, utc = core.parse_local_datetime("2026-01-01T12:00:00+00:00", "Asia/Tokyo")
    assert utc == datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert local.tzinfo == ZoneInfo("Asia/Tokyo")


def test_parse_local_datetime_rejects_garbage():
    with pytest.raises(ValueError):
        core.parse_local_datetime("next tuesday", "UTC")


def test_detect_timezone():
    assert core.detect_timezone(35.78, -78.64, None) == ("America/New_York", "location")
    assert core.detect_timezone(0, 0, "Europe/Paris") == ("Europe/Paris", "user")
    with pytest.raises(Exception):
        core.detect_timezone(0, 0, "Not/AZone")


# --- matching ------------------------------------------------------------


def test_circular_difference_wraps():
    assert core.circular_difference(179.0, -179.0) == pytest.approx(2.0)
    np.testing.assert_allclose(core.circular_difference([350.0, 10.0], 0.0), [10.0, 10.0])


def target_from(record, **overrides) -> TargetGeometry:
    values = dict(
        subearth_lon=record.subearth_lon,
        subearth_lat=record.subearth_lat,
        subsolar_lon=record.subsolar_lon,
        subsolar_lat=record.subsolar_lat,
        distance=record.distance,
        posangle=record.posangle,
    )
    values.update(overrides)
    return TargetGeometry(**values)


def test_best_frame_finds_identical_geometry(populated_cache):
    catalog = Catalog.load(populated_cache)
    wanted = catalog.records[100]
    record, score = core.find_best_historical_frame(target_from(wanted), catalog)
    assert record is wanted
    assert score == pytest.approx(0.0)


def test_best_frame_prefers_closer_geometry(populated_cache):
    catalog = Catalog.load(populated_cache)
    wanted = catalog.records[40]
    target = target_from(wanted, distance=wanted.distance + 10.0)
    record, score = core.find_best_historical_frame(target, catalog)
    assert record is wanted
    assert 0 < score < 0.01


# --- rotation ------------------------------------------------------------


def test_rotation_angle():
    assert core.rotation_angle(10.0, 10.0, 25.0, "north") == 0.0
    assert core.rotation_angle(10.0, 10.0, 25.0, "zenith") == -25.0
    assert core.rotation_angle(15.0, 10.0, 0.0, "zenith") == 5.0
    assert core.rotation_angle(0.0, 0.0, -190.0, "zenith") == pytest.approx(-170.0)
    with pytest.raises(ValueError):
        core.rotation_angle(0, 0, 0, "south")


def test_rotate_image_keeps_size_and_background(tmp_path):
    src = tmp_path / "in.jpg"
    img = Image.new("RGB", (730, 730), (0, 0, 0))
    img.paste((180, 180, 180), (165, 165, 565, 565))  # a "Moon" inset in black sky
    img.save(src, quality=95)

    out = tmp_path / "out.jpg"
    core.rotate_image(src, out, 37.0)
    rotated = Image.open(out)
    assert rotated.size == (730, 730)
    corners = np.asarray(rotated)[:10, :10]
    assert corners.max() <= 2  # JPEG noise only; fill matches NASA black


def test_background_color_follows_source():
    img = Image.new("RGB", (100, 100), (3, 4, 5))
    img.paste((200, 200, 200), (30, 30, 70, 70))
    assert core.background_color(img) == (3, 4, 5)


def test_rotate_image_direction(tmp_path):
    src = tmp_path / "in.png"
    img = Image.new("RGB", (101, 101))
    img.putpixel((50, 5), (255, 0, 0))  # marker near the top
    img.save(src)

    out = tmp_path / "out.png"
    core.rotate_image(src, out, -90.0)  # clockwise: top -> right
    rotated = np.asarray(Image.open(out))
    y, x = np.unravel_index(np.argmax(rotated[..., 0]), rotated.shape[:2])
    assert x > 85 and abs(y - 50) <= 2


# --- render_moon (network and ephemeris mocked) -------------------------


@pytest.fixture
def offline(monkeypatch, populated_cache):
    """Patch out ephemeris, NASA frame lookup and downloads."""

    catalog = Catalog.load(populated_cache)
    future_match = catalog.records[30]

    monkeypatch.setattr(
        core,
        "compute_target_geometry",
        lambda utc_dt, root, ephemeris_file=None: target_from(future_match, posangle=25.0),
    )
    monkeypatch.setattr(core, "check_date_supported", lambda *a, **k: None)
    monkeypatch.setattr(
        core,
        "compute_observer_geometry",
        lambda *a, **k: ObserverGeometry(altitude=40.0, azimuth=180.0, parallactic_angle=12.0),
    )
    monkeypatch.setattr(core.cat, "image_url", lambda paths, r: f"https://example/moon.{r.frame_number:04d}.jpg")

    downloads = []

    def fake_download(url, dest):
        downloads.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), (200, 200, 200)).save(dest, format="JPEG")

    monkeypatch.setattr(core, "download_file", fake_download)
    return populated_cache, future_match, downloads


def test_render_official(offline):
    cache, _, downloads = offline
    result = core.render_moon(
        datetime(2020, 1, 2, 3, 10, tzinfo=UTC), 35.78, -78.64, cache_dir=cache.root
    )
    assert result.status == "official"
    assert result.source.time_utc == datetime(2020, 1, 2, 3, tzinfo=UTC)
    assert result.match_score == 0.0
    # Official frame: only the parallactic rotation applies.
    assert result.rotation_degrees == pytest.approx(-12.0)
    assert result.image.exists() and result.image.parent == cache.results
    assert downloads == [f"https://example/moon.{result.source.frame_number:04d}.jpg"]

    payload = json.loads(result.result_json.read_text())
    assert payload["status"] == "official"
    assert payload["observer"]["above_horizon"] is True


def test_render_estimated(offline, tmp_path):
    cache, future_match, _ = offline
    out = tmp_path / "moon.png"
    result = core.render_moon(
        "2035-05-01 22:00", 35.78, -78.64, cache_dir=cache.root, output=out, orientation="north"
    )
    assert result.status == "estimated"
    assert (result.source.year, result.source.index) == (future_match.year, future_match.index)
    assert result.rotation_degrees == pytest.approx(25.0 - future_match.posangle)
    assert result.image == out and out.exists()
    assert result.notes


def test_render_without_image(offline):
    cache, _, downloads = offline
    result = core.render_moon("2035-05-01 22:00", 35.78, -78.64, cache_dir=cache.root, download_image=False)
    assert result.image is None and downloads == []
    json.dumps(result.to_dict())  # serializable


def test_render_bootstraps_empty_cache(monkeypatch, cache):
    called = []

    def fake_bootstrap(paths):
        called.append(paths)
        raise RuntimeError("stop here")

    monkeypatch.setattr(core.cat, "bootstrap_metadata", fake_bootstrap)
    with pytest.raises(RuntimeError, match="stop here"):
        core.render_moon("2020-01-01 00:00", 0, 0, cache_dir=cache.root, timezone_name="UTC")
    assert called


def test_aware_datetime_over_ocean_falls_back_to_utc(offline):
    cache, _, _ = offline
    result = core.render_moon(
        datetime(2020, 1, 2, 3, tzinfo=UTC), 0.0, -140.0, cache_dir=cache.root, download_image=False
    )
    assert result.timezone in ("UTC", "Etc/GMT+9")  # ocean coordinates may map to an Etc/ zone


# --- place names ---------------------------------------------------------


@pytest.fixture
def fake_geocode(monkeypatch):
    from dial_a_moon_wrapper.geocoding import Place

    def fake(query, paths):
        return Place(query, "Raleigh, North Carolina, United States", 35.78, -78.64, "nominatim")

    monkeypatch.setattr(core, "geocode", fake)


def test_render_with_place(offline, fake_geocode):
    cache, _, _ = offline
    result = core.render_moon("2020-01-02 10:00", place="Raleigh, NC", cache_dir=cache.root, download_image=False)
    assert (result.latitude, result.longitude) == (35.78, -78.64)
    assert result.timezone == "America/New_York"
    assert result.to_dict()["request"]["place"].startswith("Raleigh")


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(place="Raleigh, NC", latitude=1.0),
        dict(latitude=1.0),
        dict(),
    ],
)
def test_render_location_arguments_validated(offline, kwargs):
    cache, _, _ = offline
    with pytest.raises(ValueError):
        core.render_moon("2020-01-02 10:00", cache_dir=cache.root, download_image=False, **kwargs)
