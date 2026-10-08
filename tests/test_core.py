import os
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from PIL import Image

from dial_a_moon_wrapper import core
from dial_a_moon_wrapper.catalog import Catalog
from dial_a_moon_wrapper.geometry import LunarPhase, ObserverGeometry, PhaseEvent, TargetGeometry

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
    monkeypatch.setattr(
        core,
        "compute_lunar_phase",
        lambda utc_dt, root, ephemeris_file=None: LunarPhase(
            name="Waxing Gibbous",
            illumination=75.0,
            elongation=120.0,
            previous=PhaseEvent("First Quarter", utc_dt - timedelta(days=3)),
            next=PhaseEvent("Full Moon", utc_dt + timedelta(days=4)),
        ),
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
    assert result.image.exists()
    assert result.image.parent == cache.results / "zenith" / "730"
    assert result.image.name == "20200102T0310Z_+35.78_-78.64.jpg"
    assert downloads == [f"https://example/moon.{result.source.frame_number:04d}.jpg"]

    payload = json.loads(result.result_json.read_text())
    assert payload["status"] == "official"
    assert payload["observer"]["above_horizon"] is True
    assert payload["phase"]["name"] == "Waxing Gibbous"
    assert payload["phase"]["previous"] == {
        "name": "First Quarter",
        "local_datetime": "2019-12-29T22:10:00-05:00",
        "utc_datetime": "2019-12-30T03:10:00+00:00",
    }
    assert payload["phase"]["next"]["name"] == "Full Moon"


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


def test_coordinates_rounded(offline):
    cache, _, _ = offline
    result = core.render_moon(
        "2035-05-01 22:00", 35.78449, -78.63551, cache_dir=cache.root, download_image=False
    )
    assert (result.latitude, result.longitude) == (35.78, -78.64)
    assert result.to_dict()["request"]["latitude"] == 35.78


def test_time_rounded_to_minute(offline):
    cache, _, _ = offline
    result = core.render_moon(
        datetime(2020, 1, 2, 3, 10, 31, tzinfo=UTC), 35.78, -78.64,
        cache_dir=cache.root, download_image=False,
    )
    assert result.utc_datetime == datetime(2020, 1, 2, 3, 11, tzinfo=UTC)


def test_cached_result_reused(offline):
    cache, _, downloads = offline
    when = datetime(2020, 1, 2, 3, 10, tzinfo=UTC)
    first = core.render_moon(when, 35.78, -78.64, cache_dir=cache.root)
    first.image.write_bytes(b"cached")  # would be overwritten if regenerated

    again = core.render_moon(
        when + timedelta(seconds=20), 35.781, -78.641, cache_dir=cache.root
    )
    assert again.image == first.image
    assert again.image.read_bytes() == b"cached"
    assert len(downloads) == 1


def test_cached_result_from_other_frame_regenerated(offline):
    cache, _, _ = offline
    when = datetime(2020, 1, 2, 3, 10, tzinfo=UTC)
    first = core.render_moon(when, 35.78, -78.64, cache_dir=cache.root)
    first.image.write_bytes(b"stale")
    payload = json.loads(first.result_json.read_text())
    payload["source"]["frame"] += 1
    first.result_json.write_text(json.dumps(payload))

    core.render_moon(when, 35.78, -78.64, cache_dir=cache.root)
    assert first.image.read_bytes() != b"stale"


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


# --- resolution ----------------------------------------------------------


def test_square_frame_crops_and_keeps_transparency():
    frame = Image.new("RGBA", (192, 108), (0, 0, 0, 0))  # transparent 16:9
    frame.paste((200, 180, 160, 255), (66, 24, 126, 84))  # opaque centered "Moon"
    out = core.square_frame(frame)
    assert out.mode == "RGBA" and out.size == (108, 108)
    a = np.asarray(out)
    assert a[0, 0, 3] == 0  # still transparent
    assert a[54, 54].tolist() == [200, 180, 160, 255]


def test_square_frame_leaves_730_frames_alone():
    frame = Image.new("RGB", (730, 730), (5, 5, 5))
    out = core.square_frame(frame)
    assert out.size == (730, 730) and out.mode == "RGB"


def _highres_source(tmp_path):
    src = tmp_path / "moon.tif"
    frame = Image.new("RGBA", (192, 108), (0, 0, 0, 0))
    frame.paste((200, 180, 160, 255), (66, 24, 126, 84))
    frame.save(src, format="TIFF")
    return src


def test_rotate_highres_png_stays_transparent(tmp_path):
    out = tmp_path / "out.png"
    assert core.rotate_image(_highres_source(tmp_path), out, 30.0) is False
    rotated = Image.open(out)
    a = np.asarray(rotated)
    assert rotated.mode == "RGBA" and rotated.size == (108, 108)
    assert a[0, 0, 3] == 0 and a[54, 54, 3] == 255


def test_rotate_highres_to_jpeg_is_flattened_onto_black(tmp_path):
    out = tmp_path / "out.jpg"
    assert core.rotate_image(_highres_source(tmp_path), out, 30.0) is True
    rotated = Image.open(out)
    assert rotated.mode == "RGB" and np.asarray(rotated)[:5, :5].max() <= 2


def test_render_highres_with_fallback(offline, monkeypatch):
    cache, _, downloads = offline
    monkeypatch.setattr(
        core.cat, "highres_image_url",
        lambda paths, r, width: (f"https://example/1920/moon.{r.frame_number:04d}.tif", 1920),
    )

    def fake_download(url, dest):
        downloads.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (192, 108), (0, 0, 0, 0)).save(dest, format="TIFF")

    monkeypatch.setattr(core, "download_file", fake_download)
    result = core.render_moon("2020-01-02 10:00", 35.78, -78.64, cache_dir=cache.root, resolution=5760)

    assert result.resolution == 1920 and result.requested_resolution == 5760
    assert result.source_image.parent.name == "1920"
    assert result.image.suffix == ".png"
    rendered = Image.open(result.image)
    assert rendered.size == (108, 108) and rendered.mode == "RGBA"
    assert any("next largest available size, 1920" in n for n in result.notes)
    payload = result.to_dict()
    assert payload["request"]["resolution"] == 5760 and payload["resolution"] == 1920


def test_reused_frame_is_marked_used(tmp_path):
    f = tmp_path / "moon.0001.jpg"
    f.write_bytes(b"x")
    os.utime(f, (0, 0))
    core.download_file("https://unused", f)  # cached: no network
    assert f.stat().st_mtime > 0


def test_render_rejects_unknown_resolution(offline):
    cache, _, _ = offline
    with pytest.raises(ValueError, match="resolution must be one of"):
        core.render_moon("2020-01-02 10:00", 35.78, -78.64, cache_dir=cache.root, resolution=1000)
