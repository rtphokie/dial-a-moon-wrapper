import json

import pytest

from dial_a_moon_wrapper import geocoding as gc


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, **_):
        self.calls.append(params["q"])
        return FakeResponse(self.payload)


RALEIGH = [{
    "lat": "35.7803977",
    "lon": "-78.6390989",
    "display_name": "Raleigh, Wake County, North Carolina, United States",
}]


@pytest.fixture
def session(monkeypatch):
    s = FakeSession(RALEIGH)
    monkeypatch.setattr(gc.cat, "SESSION", s)
    monkeypatch.setattr(gc, "MIN_INTERVAL", 0.0)
    return s


@pytest.mark.parametrize(
    "text, expected",
    [
        ("35.78, -78.64", (35.78, -78.64)),
        ("35.78 -78.64", (35.78, -78.64)),
        ("-33.87,151.21", (-33.87, 151.21)),
        ("Raleigh, NC", None),
    ],
)
def test_parse_coordinates(text, expected):
    assert gc.parse_coordinates(text) == expected


def test_parse_coordinates_out_of_range():
    with pytest.raises(ValueError):
        gc.parse_coordinates("95, 10")


def test_coordinates_need_no_network(cache, session):
    place = gc.geocode("35.78, -78.64", cache)
    assert (place.latitude, place.longitude, place.source) == (35.78, -78.64, "coordinates")
    assert session.calls == []


def test_geocode_and_cache(cache, session):
    place = gc.geocode("Raleigh, NC", cache)
    assert place.latitude == pytest.approx(35.7804, abs=1e-4)
    assert place.name.startswith("Raleigh, Wake County")
    assert place.source == "nominatim"

    # Case/spacing variants hit the cache; no second request.
    again = gc.geocode("  raleigh,nc ", cache)
    assert again.source == "cache" and again.latitude == place.latitude
    assert session.calls == ["Raleigh, NC"]
    assert "raleigh, nc" in json.loads(cache.geocode_cache.read_text())


def test_geocode_not_found(cache, session):
    session.payload = []
    with pytest.raises(LookupError, match="Could not find"):
        gc.geocode("Nowhere Blorfistan", cache)
    assert not cache.geocode_cache.exists()


def test_geocode_empty(cache, session):
    with pytest.raises(LookupError):
        gc.geocode("   ", cache)


@pytest.mark.network
def test_nominatim_live(cache):
    place = gc.geocode("Raleigh, NC", cache)
    assert place.latitude == pytest.approx(35.78, abs=0.2)
    assert place.longitude == pytest.approx(-78.64, abs=0.2)
