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


def test_unknown_year_raises(cache):
    with pytest.raises(RuntimeError, match="No NASA visualization ID"):
        cat.download_annual_json(cache, 1999)
