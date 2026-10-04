import json
from datetime import datetime, timezone

import pytest

from dial_a_moon_wrapper import catalog as cat
from dial_a_moon_wrapper.catalog import Catalog

from .conftest import make_nasa_item, write_year

UTC = timezone.utc

# Trimmed from https://svs.gsfc.nasa.gov/4442/ (2019). The page also links
# frames belonging to other visualizations.
PAGE_2019 = """
<a href="/vis/a000000/a004400/a004442/mooninfo_2019.json">JSON</a>
<a href="https://svs.gsfc.nasa.gov/vis/a000000/a005100/a005187/frames/730x730_1x1_30p/moon.0283.jpg">related</a>
<a href="/vis/a000000/a004400/a004442/frames/730x730_1x1_30p/">frames</a>
<a href="/vis/a000000/a004400/a004442/frames/216x216_1x1_30p/">small</a>
"""


def test_parse_nasa_time():
    assert cat.parse_nasa_time("01 Jan 2026 00:00 UT") == datetime(2026, 1, 1, tzinfo=UTC)
    assert cat.parse_nasa_time("29 Feb 2024 13:00 UT") == datetime(2024, 2, 29, 13, tzinfo=UTC)


def test_find_json_href():
    assert cat.find_json_href(PAGE_2019, 2019) == "/vis/a000000/a004400/a004442/mooninfo_2019.json"
    with pytest.raises(RuntimeError):
        cat.find_json_href(PAGE_2019, 2020)


def test_find_frames_href_ignores_other_visualizations():
    href = cat.find_frames_href(PAGE_2019, 4442)
    assert href == "/vis/a000000/a004400/a004442/frames/730x730_1x1_30p/"
    with pytest.raises(RuntimeError):
        cat.find_frames_href(PAGE_2019, 9999)


def test_image_url_uses_manifest(cache):
    cache.frame_manifest.write_text(json.dumps({"2019": "https://x/frames/730/"}))
    record = cat.MoonRecord(2019, 0, datetime(2019, 1, 1, tzinfo=UTC), *([0.0] * 11))
    assert cat.image_url(cache, record) == "https://x/frames/730/moon.0001.jpg"


def test_load_and_index(populated_cache):
    catalog = Catalog.load(populated_cache)
    assert len(catalog) == 144
    assert catalog.years == [2020, 2021]
    r = catalog.records[5]
    assert r.year == 2020 and r.index == 5 and r.frame_number == 6
    assert r.time_utc == datetime(2020, 1, 1, 5, tzinfo=UTC)


def test_load_skips_malformed_and_foreign_files(cache, caplog):
    good = make_nasa_item(datetime(2020, 1, 1, tzinfo=UTC))
    bad = {"time": "01 Jan 2020 01:00 UT"}
    cache.metadata_file(2020).write_text(json.dumps([good, bad]))
    (cache.metadata / "mooninfo_notayear.json").write_text("[]")
    catalog = Catalog.load(cache)
    assert len(catalog) == 1
    assert "skipping malformed" in caplog.text


def test_empty_catalog_raises(cache):
    with pytest.raises(RuntimeError, match="No NASA"):
        Catalog.load(cache)


@pytest.mark.parametrize(
    "minute, expected_hour",
    [(0, 10), (29, 10), (30, 11), (59, 11)],
)
def test_exact_rounds_to_nearest_hour(populated_cache, minute, expected_hour):
    catalog = Catalog.load(populated_cache)
    r = catalog.exact(datetime(2020, 1, 2, 10, minute, tzinfo=UTC))
    assert r.time_utc.hour == expected_hour


def test_exact_missing_returns_none(populated_cache):
    catalog = Catalog.load(populated_cache)
    assert catalog.exact(datetime(2030, 6, 1, tzinfo=UTC)) is None


class FakeResponse:
    def __init__(self, text="", payload=None):
        self.text = text
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def get(self, url, timeout=None, **_):
        self.urls.append(url)
        if url.endswith(".json"):
            return FakeResponse(payload=self.payload)
        return FakeResponse(text=PAGE_2019)


def test_download_annual_json_writes_data_and_manifest(cache, monkeypatch):
    data = [make_nasa_item(datetime(2019, 1, 1, tzinfo=UTC))]
    session = FakeSession(data)
    monkeypatch.setattr(cat, "SESSION", session)

    path = cat.download_annual_json(cache, 2019)

    assert json.loads(path.read_text()) == data
    assert session.urls[-1] == "https://svs.gsfc.nasa.gov/vis/a000000/a004400/a004442/mooninfo_2019.json"
    manifest = json.loads(cache.frame_manifest.read_text())
    assert manifest["2019"].endswith("/a004442/frames/730x730_1x1_30p/")

    # Cached: no further network access.
    session.urls.clear()
    cat.download_annual_json(cache, 2019)
    assert session.urls == []


def test_download_rejects_bad_json_without_clobbering(cache, monkeypatch):
    write_year(cache, 2019, hours=2)
    before = cache.metadata_file(2019).read_text()
    monkeypatch.setattr(cat, "SESSION", FakeSession({"not": "a list"}))
    with pytest.raises(RuntimeError, match="unexpected JSON"):
        cat.download_annual_json(cache, 2019, force=True)
    assert cache.metadata_file(2019).read_text() == before


def test_unpublished_year_raises(cache, monkeypatch):
    monkeypatch.setattr(cat, "SESSION", ApiSession({2026: 5587}))
    with pytest.raises(RuntimeError, match="has not published 2027"):
        cat.download_annual_json(cache, 2027)


# --- automatic new-year check -------------------------------------------

from datetime import timedelta  # noqa: E402


class ApiSession:
    """Fake NASA: the Dial-A-Moon API plus visualization pages and JSON."""

    def __init__(self, published: dict[int, int]):
        self.published = published  # year -> visualization id
        self.calls = []

    def get(self, url, timeout=None, **_):
        self.calls.append(url)
        if "/api/dialamoon/" in url:
            year = int(url.rsplit("/", 1)[1][:4])
            if year in self.published:
                vid = self.published[year]
                return FakeResponse(payload={
                    "time": f"{year}-01-01T00:00",
                    "image": {"url": f"https://svs.gsfc.nasa.gov/vis/a000000/a005600/a{vid:06d}/frames/730x730_1x1_30p/moon.0001.jpg"},
                })
            last = max(self.published)
            return FakeResponse(payload={
                "time": f"{last}-12-31T23:00",
                "image": {"url": "https://svs.gsfc.nasa.gov/vis/a000000/a005500/a005587/frames/730x730_1x1_30p/moon.8760.jpg"},
            })
        if url.endswith(".json"):
            year = int(url.rsplit("_", 1)[1][:4])
            return FakeResponse(payload=[make_nasa_item(datetime(year, 1, 1, tzinfo=UTC))])
        vid = int(url.rstrip("/").rsplit("/", 1)[1])
        year = next(y for y, v in self.published.items() if v == vid)
        return FakeResponse(text=(
            f'<a href="/vis/a000000/a005600/a{vid:06d}/mooninfo_{year}.json">JSON</a>'
            f'<a href="/vis/a000000/a005600/a{vid:06d}/frames/730x730_1x1_30p/">frames</a>'
        ))


def test_discover_visualization_id(monkeypatch):
    monkeypatch.setattr(cat, "SESSION", ApiSession({2026: 5587, 2027: 5650}))
    assert cat.discover_visualization_id(2027) == 5650
    monkeypatch.setattr(cat, "SESSION", ApiSession({2026: 5587}))
    assert cat.discover_visualization_id(2027) is None  # API clamps to 2026


def test_no_next_year_check_before_october(cache, monkeypatch):
    write_year(cache, 2026, hours=1)
    session = ApiSession({2026: 5587, 2027: 5650})
    monkeypatch.setattr(cat, "SESSION", session)
    assert cat.check_for_new_years(cache, now=datetime(2026, 9, 30, tzinfo=UTC)) == []
    assert session.calls == []


def test_next_year_found_in_october_and_cached(cache, monkeypatch):
    write_year(cache, 2026, hours=1)
    monkeypatch.setattr(cat, "SESSION", ApiSession({2026: 5587, 2027: 5650}))

    added = cat.check_for_new_years(cache, now=datetime(2026, 10, 4, tzinfo=UTC))

    assert added == [2027]
    assert cache.metadata_file(2027).exists()
    assert cat.known_visualizations(cache)[2027] == 5650
    assert json.loads(cache.frame_manifest.read_text())["2027"].endswith("/a005650/frames/730x730_1x1_30p/")


def test_check_runs_at_most_once_per_day(cache, monkeypatch):
    write_year(cache, 2026, hours=1)
    session = ApiSession({2026: 5587})  # 2027 not yet published
    monkeypatch.setattr(cat, "SESSION", session)
    t0 = datetime(2026, 10, 4, 8, tzinfo=UTC)

    assert cat.check_for_new_years(cache, now=t0) == []
    assert len(session.calls) == 1

    cat.check_for_new_years(cache, now=t0 + timedelta(hours=23, minutes=59))
    assert len(session.calls) == 1  # throttled

    cat.check_for_new_years(cache, now=t0 + timedelta(days=1))
    assert len(session.calls) == 2  # next day: checks again


def test_failed_check_still_throttled(cache, monkeypatch):
    write_year(cache, 2026, hours=1)

    class Down:
        calls = 0

        def get(self, *a, **k):
            Down.calls += 1
            raise ConnectionError("NASA unreachable")

    monkeypatch.setattr(cat, "SESSION", Down())
    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    assert cat.check_for_new_years(cache, now=t0) == []
    cat.check_for_new_years(cache, now=t0 + timedelta(hours=2))
    assert Down.calls == 1


def test_no_check_when_everything_cached(cache, monkeypatch):
    write_year(cache, 2026, hours=1)
    write_year(cache, 2027, hours=1)
    session = ApiSession({2026: 5587, 2027: 5650})
    monkeypatch.setattr(cat, "SESSION", session)
    assert cat.check_for_new_years(cache, now=datetime(2026, 12, 1, tzinfo=UTC)) == []
    assert session.calls == [] and not cache.update_check.exists()


def test_missing_current_year_checked_in_january(cache, monkeypatch):
    write_year(cache, 2026, hours=1)
    monkeypatch.setattr(cat, "SESSION", ApiSession({2026: 5587, 2027: 5650}))
    assert cat.check_for_new_years(cache, now=datetime(2027, 1, 5, tzinfo=UTC)) == [2027]


# --- resilience to NASA format changes ----------------------------------


class ScriptedSession:
    """Returns canned replies by URL substring."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, timeout=None, **_):
        self.calls.append(url)
        for key, reply in self.routes.items():
            if key in url:
                return reply
        raise AssertionError(f"unexpected URL {url}")


@pytest.mark.parametrize(
    "payload",
    [
        "<html>maintenance</html>",
        ["not", "a", "dict"],
        {"time": "2027-01-01T00:00", "image": "a-string-now"},
        {"time": "2027-01-01T00:00", "image": {"url": None}},
        {"time": "2027-01-01T00:00", "image": {"url": "https://svs.gsfc.nasa.gov/new/layout/moon.jpg"}},
        {"when": "2027-01-01"},
    ],
)
def test_discovery_survives_api_format_changes(payload, monkeypatch):
    monkeypatch.setattr(cat, "SESSION", ScriptedSession({"/api/": FakeResponse(payload=payload)}))
    assert cat.discover_visualization_id(2027) is None


def test_api_returning_non_json_does_not_raise_from_check(cache, monkeypatch):
    write_year(cache, 2026, hours=1)

    class BadJson(FakeResponse):
        def json(self):
            raise ValueError("Expecting value")

    monkeypatch.setattr(cat, "SESSION", ScriptedSession({"/api/": BadJson()}))
    assert cat.check_for_new_years(cache, now=datetime(2026, 11, 1, tzinfo=UTC)) == []


def test_wrong_discovered_id_is_not_persisted(cache, monkeypatch):
    write_year(cache, 2026, hours=1)
    api = FakeResponse(payload={
        "time": "2027-01-01T00:00",
        "image": {"url": "https://svs.gsfc.nasa.gov/vis/a000000/a009900/a009999/frames/730x730_1x1_30p/moon.0001.jpg"},
    })
    page_without_json = FakeResponse(text="<html>some other visualization</html>")
    monkeypatch.setattr(cat, "SESSION", ScriptedSession({"/api/": api, "/9999/": page_without_json}))

    assert cat.check_for_new_years(cache, now=datetime(2026, 11, 1, tzinfo=UTC)) == []
    assert 2027 not in cat.known_visualizations(cache)  # rediscovered tomorrow


def test_corrupt_check_file_does_not_block_checks(cache, monkeypatch):
    write_year(cache, 2026, hours=1)
    cache.update_check.write_text('{"last_check": "not a date"}')
    session = ApiSession({2026: 5587})
    monkeypatch.setattr(cat, "SESSION", session)
    cat.check_for_new_years(cache, now=datetime(2026, 11, 1, tzinfo=UTC))
    assert len(session.calls) == 1


def test_image_url_falls_back_to_api_when_frames_dir_missing(cache, monkeypatch):
    record = cat.MoonRecord(2027, 99, datetime(2027, 1, 5, 3, tzinfo=UTC), *([0.0] * 11))
    cache.visualizations.write_text('{"2027": 5650}')
    api_url = "https://svs.gsfc.nasa.gov/vis/a000000/a005600/a005650/frames/1024x1024_new/moon.0100.jpg"
    monkeypatch.setattr(cat, "SESSION", ScriptedSession({
        "/5650/": FakeResponse(text="<html>frames renamed</html>"),
        "/api/dialamoon/2027-01-05T03:00": FakeResponse(payload={
            "time": "2027-01-05T03:00", "image": {"url": api_url},
        }),
    }))
    assert cat.image_url(cache, record) == api_url


def test_image_url_raises_clearly_when_nothing_works(cache, monkeypatch):
    record = cat.MoonRecord(2027, 0, datetime(2027, 1, 1, tzinfo=UTC), *([0.0] * 11))
    cache.visualizations.write_text('{"2027": 5650}')
    monkeypatch.setattr(cat, "SESSION", ScriptedSession({
        "/5650/": FakeResponse(text="<html></html>"),
        "/api/": FakeResponse(payload={"time": "2026-12-31T23:00", "image": {"url": "x"}}),
    }))
    with pytest.raises(RuntimeError, match="NASA has no image for 2027-01-01T00:00"):
        cat.image_url(cache, record)


# --- high-resolution frames ---------------------------------------------

PAGE_2012 = """
<a href="/vis/a000000/a003800/a003894/frames/1920x1080_16x9_30p/moon/">partial 30p set</a>
<a href="/vis/a000000/a003800/a003894/frames/1920x1080_16x9_30p/comp/">composite</a>
<a href="/vis/a000000/a003800/a003894/frames/1920x1080_16x9_60p/">full 60p set</a>
<a href="/vis/a000000/a003800/a003894/frames/730x730_1x1_60p/">730</a>
"""

PAGE_2015 = """
<a href="/vis/a000000/a004200/a004236/frames/1080x1080_1x1_30p/">orbit diagram</a>
<a href="/vis/a000000/a004200/a004236/frames/1920x1080_16x9_30p/fancy/">fancy</a>
<a href="/vis/a000000/a004200/a004236/frames/1920x1080_16x9_30p/plain/">plain</a>
<a href="/vis/a000000/a004200/a004236/frames/5760x3240_16x9_30p/labels/">labels</a>
<a href="/vis/a000000/a004200/a004236/frames/5760x3240_16x9_30p/plain/">plain</a>
<a href="/vis/a000000/a004200/a004236/frames/730x730_1x1_30p/">730</a>
"""


def test_find_highres_href_2012_uses_full_60p_set():
    assert cat.find_highres_href(PAGE_2012, 3894, 1920) == "/vis/a000000/a003800/a003894/frames/1920x1080_16x9_60p/"
    assert cat.find_highres_href(PAGE_2012, 3894, 5760) is None


def test_find_highres_href_prefers_plain_and_reports_missing():
    assert cat.find_highres_href(PAGE_2015, 4236, 1920).endswith("/1920x1080_16x9_30p/plain/")
    assert cat.find_highres_href(PAGE_2015, 4236, 3840) is None
    assert cat.find_highres_href(PAGE_2015, 4236, 5760).endswith("/5760x3240_16x9_30p/plain/")


def _record(year, index=99):
    return cat.MoonRecord(year, index, datetime(year, 1, 5, 3, tzinfo=UTC), *([0.0] * 11))


def test_highres_falls_back_to_next_largest_available(cache, monkeypatch):
    session = ScriptedSession({"/4236/": FakeResponse(text=PAGE_2015)})
    monkeypatch.setattr(cat, "SESSION", session)

    url, used = cat.highres_image_url(cache, _record(2015), 3840)
    assert used == 1920 and url.endswith("/1920x1080_16x9_30p/plain/moon.0100.tif")

    url, used = cat.highres_image_url(cache, _record(2015), 5760)
    assert used == 5760 and url.endswith("/5760x3240_16x9_30p/plain/moon.0100.tif")
    assert len(session.calls) == 1  # all sizes recorded from one page visit


def test_highres_none_available(cache, monkeypatch):
    monkeypatch.setattr(cat, "SESSION", ScriptedSession({"/4236/": FakeResponse(text="<html></html>")}))
    assert cat.highres_image_url(cache, _record(2015), 5760) == (None, 730)
