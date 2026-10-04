import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from dial_a_moon_wrapper.paths import CachePaths

DATA = Path(__file__).parent / "data"


def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        help="Run tests that contact svs.gsfc.nasa.gov.",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return
    skip = pytest.mark.skip(reason="needs --run-network")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


def make_nasa_item(dt: datetime, **overrides) -> dict:
    """A NASA mooninfo JSON entry with smoothly varying fake geometry."""

    h = (dt - datetime(2000, 1, 1, tzinfo=timezone.utc)).total_seconds() / 3600
    item = {
        "time": dt.strftime("%d %b %Y %H:%M UT"),
        "phase": 50.0,
        "age": 7.0,
        "diameter": 1850.0,
        "distance": 380000.0 + 20000.0 * math.sin(h / 50.0),
        "j2000": {"ra": 12.0, "dec": 0.0},
        "subsolar": {
            "lon": ((h * 0.508) + 180.0) % 360.0 - 180.0,
            "lat": 1.5 * math.sin(h / 4000.0),
        },
        "subearth": {"lon": 7.0 * math.sin(h / 100.0), "lat": 6.5 * math.cos(h / 110.0)},
        "posangle": 10.0,
    }
    item.update(overrides)
    return item


def write_year(paths: CachePaths, year: int, hours: int = 72) -> list[dict]:
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    data = [make_nasa_item(start + timedelta(hours=i)) for i in range(hours)]
    paths.metadata.mkdir(parents=True, exist_ok=True)
    paths.metadata_file(year).write_text(json.dumps(data))
    return data


@pytest.fixture
def cache(tmp_path) -> CachePaths:
    return CachePaths(tmp_path / "cache").ensure()


@pytest.fixture
def populated_cache(cache) -> CachePaths:
    write_year(cache, 2020)
    write_year(cache, 2021)
    return cache


@pytest.fixture(scope="session")
def reference_records() -> list[dict]:
    return json.loads((DATA / "nasa_reference_records.json").read_text())


@pytest.fixture(scope="session")
def ephemeris_root(tmp_path_factory):
    """
    A cache root whose ephemeris is loadable. Honors DIALAMOON_EPHEMERIS;
    otherwise downloads de421 once per session. Skips when unavailable.
    """

    from dial_a_moon_wrapper.geometry import load_ephemeris

    root = tmp_path_factory.mktemp("ephem")
    try:
        load_ephemeris(root)
    except Exception as exc:  # offline
        pytest.skip(f"ephemeris unavailable: {exc}")
    return root
