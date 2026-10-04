"""Live checks against NASA SVS. Run with ``pytest --run-network``."""

import pytest

from dial_a_moon_wrapper import catalog as cat

pytestmark = pytest.mark.network


@pytest.mark.parametrize("year", [2011, 2019, max(cat.ANNUAL_VISUALIZATIONS)])
def test_visualization_pages_resolve(year):
    vid = cat.ANNUAL_VISUALIZATIONS[year]
    assert cat.discover_json_url(year, vid).endswith(f"mooninfo_{year}.json")
    frames = cat.discover_frames_url(vid)
    response = cat.SESSION.head(frames + "moon.0001.jpg", timeout=cat.REQUEST_TIMEOUT)
    assert response.status_code == 200
