"""
NASA SVS annual Moon Phase and Libration catalog.

Network access happens only in the bootstrap/download functions. Lookups
run entirely against the locally cached annual JSON files.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import numpy as np
import requests

from ._version import __version__
from .paths import CachePaths

log = logging.getLogger(__name__)

NASA_BASE = "https://svs.gsfc.nasa.gov"
REQUEST_TIMEOUT = 30
FIRST_YEAR = 2011

# NASA publishes the following year's visualization around November.
# From this month on, look for it at most once per UPDATE_CHECK_INTERVAL.
NEXT_YEAR_CHECK_MONTH = 10
UPDATE_CHECK_INTERVAL = timedelta(days=1)

# NASA annual Dial-A-Moon visualization IDs.
#
# These are deliberately kept here rather than trying to infer the
# visualization ID from the year. NASA's IDs are not sequential by year.
ANNUAL_VISUALIZATIONS = {
    2011: 3810,
    2012: 3894,
    2013: 4000,
    2014: 4118,
    2015: 4236,
    2016: 4404,
    2017: 4537,
    2018: 4604,
    2019: 4442,
    2020: 4768,
    2021: 4874,
    2022: 4955,
    2023: 5048,
    2024: 5187,
    2025: 5415,
    2026: 5587,
}

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            f"dial-a-moon-wrapper/{__version__} "
            "(NASA SVS Dial-A-Moon research utility)"
        )
    }
)


@dataclass
class MoonRecord:
    year: int
    index: int
    time_utc: datetime
    phase: float
    age: float
    diameter: float
    distance: float
    ra: float
    dec: float
    subsolar_lon: float
    subsolar_lat: float
    subearth_lon: float
    subearth_lat: float
    posangle: float

    @property
    def frame_number(self) -> int:
        """NASA frame numbers are 1-based hours of the year."""
        return self.index + 1


def parse_nasa_time(value: str) -> datetime:
    """
    Parse NASA's annual JSON timestamp.

    Example:
        01 Jan 2026 00:00 UT
    """

    value = value.replace(" UT", "").strip()
    dt = datetime.strptime(value, "%d %b %Y %H:%M")
    return dt.replace(tzinfo=timezone.utc)


def _fetch_page(visualization_id: int) -> tuple[str, str]:
    page_url = f"{NASA_BASE}/{visualization_id}/"
    response = SESSION.get(page_url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return page_url, response.text


def find_json_href(html: str, year: int) -> str:
    """Return the href of ``mooninfo_<year>.json`` within a page."""

    marker = f"mooninfo_{year}.json"
    match = re.search(rf'href="([^"]*{re.escape(marker)})"', html)
    if match is None:
        raise RuntimeError(f"Could not find {marker} on NASA page")
    return match.group(1)


def find_frames_href(html: str, visualization_id: int) -> str:
    """
    Return the href of the visualization's own 730x730 frame directory.

    Pages also link to frames of *other* visualizations (e.g. the
    "related" carousel), so the match is restricted to this ID's
    ``/a00NNNN/`` path. 2011-2012 use ``_60p``, later years ``_30p``.
    """

    vis_dir = f"a{visualization_id:06d}"
    candidates = re.findall(
        rf'href="([^"]*/{vis_dir}/frames/730x730_[^"/]*/)"', html
    )
    if not candidates:
        raise RuntimeError(
            f"Could not find 730x730 frame directory for "
            f"visualization {visualization_id}"
        )
    return sorted(candidates)[0]


def discover_json_url(year: int, visualization_id: int) -> str:
    """
    Retrieve the NASA visualization page and discover its annual
    mooninfo JSON link.

    This avoids hard-coding NASA's /vis/a... path, which has changed
    between visualization years.
    """

    page_url, html = _fetch_page(visualization_id)
    return urljoin(page_url, find_json_href(html, year))


def discover_frames_url(visualization_id: int) -> str:
    page_url, html = _fetch_page(visualization_id)
    return urljoin(page_url, find_frames_href(html, visualization_id))


def _read_manifest(paths: CachePaths) -> dict[str, str]:
    return _read_json(paths.frame_manifest)


def _write_manifest(paths: CachePaths, manifest: dict[str, str]) -> None:
    _write_json(paths.frame_manifest, manifest)


def frames_url(paths: CachePaths, year: int) -> str:
    """
    Return the 730x730 frame directory for ``year``, discovering and
    caching it in ``metadata/frames.json`` on first use.
    """

    manifest = _read_manifest(paths)
    key = str(year)
    if key not in manifest:
        vid = known_visualizations(paths).get(year)
        if vid is None:
            raise RuntimeError(f"No NASA visualization ID is known for {year}")
        manifest[key] = discover_frames_url(vid)
        _write_manifest(paths, manifest)
    return manifest[key]


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def known_visualizations(paths: CachePaths) -> dict[int, int]:
    """Built-in visualization IDs plus any discovered and cached since."""

    discovered = {
        int(year): int(vid)
        for year, vid in _read_json(paths.visualizations).items()
    }
    return {**discovered, **ANNUAL_VISUALIZATIONS}


def discover_visualization_id(year: int) -> Optional[int]:
    """
    Ask NASA's Dial-A-Moon API which visualization holds ``year``.

    For a year NASA hasn't published, the API returns the last frame it
    has (e.g. 2026-12-31T23:00 for a 2027 request), so the year is only
    accepted when the returned time falls inside it.
    """

    response = SESSION.get(
        f"{NASA_BASE}/api/dialamoon/{year}-01-01T00:00",
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    time_text, url = _api_frame(response.json())

    if not time_text.startswith(f"{year}-"):
        return None

    match = re.search(r"/a(\d{6})/frames/", url)
    return int(match.group(1)) if match else None


def _api_frame(data) -> tuple[str, str]:
    """(time, 730x730 image URL) from a Dial-A-Moon API reply, or ("", "")."""

    if not isinstance(data, dict):
        return "", ""
    image = data.get("image")
    url = image.get("url") if isinstance(image, dict) else None
    return str(data.get("time", "")), url if isinstance(url, str) else ""


def api_image_url(record: MoonRecord) -> str:
    """
    Ask the Dial-A-Moon API for a frame's image URL. Used when a year's
    frame directory can't be found on its page.
    """

    stamp = f"{record.time_utc:%Y-%m-%dT%H:%M}"
    response = SESSION.get(f"{NASA_BASE}/api/dialamoon/{stamp}", timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    time_text, url = _api_frame(response.json())
    if not time_text.startswith(stamp) or not url:
        raise RuntimeError(f"NASA has no image for {stamp}")
    return url


def image_url(paths: CachePaths, record: MoonRecord) -> str:
    try:
        directory = frames_url(paths, record.year)
    except Exception as exc:
        log.info("%s: frame directory unavailable (%s); asking the API", record.year, exc)
        return api_image_url(record)
    return urljoin(directory, f"moon.{record.frame_number:04d}.jpg")


def download_annual_json(
    paths: CachePaths,
    year: int,
    force: bool = False,
) -> Path:
    """
    Download one annual NASA JSON file if it is not already cached.
    """

    destination = paths.metadata_file(year)

    if destination.exists() and not force:
        log.debug("%s: cached", year)
        return destination

    visualization_id = known_visualizations(paths).get(year)
    newly_discovered = visualization_id is None

    if newly_discovered:
        visualization_id = discover_visualization_id(year)
        if visualization_id is None:
            raise RuntimeError(f"NASA has not published {year} yet")
        log.info("%s: found NASA visualization %s", year, visualization_id)

    log.info("%s: discovering NASA JSON...", year)

    page_url, html = _fetch_page(visualization_id)
    json_url = urljoin(page_url, find_json_href(html, year))

    # Record the frame directory while we have the page in hand.
    try:
        manifest = _read_manifest(paths)
        manifest[str(year)] = urljoin(
            page_url, find_frames_href(html, visualization_id)
        )
        _write_manifest(paths, manifest)
    except RuntimeError as exc:
        log.warning("%s: %s", year, exc)

    log.info("%s: downloading %s", year, json_url)

    response = SESSION.get(json_url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    # Validate before replacing the cached copy.
    data = response.json()

    if not isinstance(data, list) or not data:
        raise RuntimeError(f"NASA returned unexpected JSON for {year}")

    temporary = destination.with_suffix(".tmp")

    with temporary.open("w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))

    temporary.replace(destination)

    # Remember a discovered ID only once it has proven to hold the data,
    # so a wrong guess is rediscovered next time rather than cached.
    if newly_discovered:
        discovered = _read_json(paths.visualizations)
        discovered[str(year)] = visualization_id
        _write_json(paths.visualizations, discovered)

    log.info("%s: cached %s records", year, f"{len(data):,}")

    return destination


def bootstrap_metadata(
    paths: CachePaths,
    current_year: Optional[int] = None,
    force: bool = False,
) -> None:
    """
    Populate the local catalog.

    Historical years are downloaded once (or again with ``force``).

    The current year is downloaded if available.

    Beginning in October, also check for the next year's annual
    visualization. If it is not published yet, leave it absent.
    """

    paths.ensure()
    now = datetime.now(timezone.utc)
    current_year = current_year or now.year

    for year in range(FIRST_YEAR, current_year + 1):
        try:
            download_annual_json(paths, year, force=force)
        except Exception as exc:
            log.warning("unable to obtain %s: %s", year, exc)

    if now.month >= NEXT_YEAR_CHECK_MONTH:
        try:
            download_annual_json(paths, current_year + 1, force=force)
        except Exception as exc:
            log.info("%s: not yet available: %s", current_year + 1, exc)


def check_for_new_years(
    paths: CachePaths,
    now: Optional[datetime] = None,
) -> list[int]:
    """
    Fetch newly published annual files, at most once per day.

    The current year is checked whenever it is missing from the cache;
    from October on the following year is checked too. Each attempt is
    recorded in ``metadata/update_check.json`` before any network
    access, so an unreachable NASA site is not retried until the next
    day either. Returns the years that were newly cached.
    """

    now = now or datetime.now(timezone.utc)
    wanted = [now.year]
    if now.month >= NEXT_YEAR_CHECK_MONTH:
        wanted.append(now.year + 1)

    missing = [y for y in wanted if not paths.metadata_file(y).exists()]
    if not missing:
        return []

    try:
        last = datetime.fromisoformat(_read_json(paths.update_check)["last_check"])
    except (KeyError, TypeError, ValueError):
        last = None
    if last is not None and now - last < UPDATE_CHECK_INTERVAL:
        return []

    _write_json(paths.update_check, {"last_check": now.isoformat()})

    added = []
    for year in missing:
        try:
            download_annual_json(paths, year)
            added.append(year)
        except Exception as exc:
            log.info("%s: not yet available: %s", year, exc)
    return added


def has_metadata(paths: CachePaths) -> bool:
    return paths.metadata.is_dir() and any(
        paths.metadata.glob("mooninfo_*.json")
    )


def _record_from_json(year: int, index: int, item: dict) -> MoonRecord:
    return MoonRecord(
        year=year,
        index=index,
        time_utc=parse_nasa_time(item["time"]),
        phase=float(item["phase"]),
        age=float(item["age"]),
        diameter=float(item["diameter"]),
        distance=float(item["distance"]),
        ra=float(item["j2000"]["ra"]),
        dec=float(item["j2000"]["dec"]),
        subsolar_lon=float(item["subsolar"]["lon"]),
        subsolar_lat=float(item["subsolar"]["lat"]),
        subearth_lon=float(item["subearth"]["lon"]),
        subearth_lat=float(item["subearth"]["lat"]),
        posangle=float(item["posangle"]),
    )


class Catalog:
    """
    In-memory view of every cached annual file, with an hourly time
    index for exact lookups and NumPy columns for geometry matching.
    """

    def __init__(self, records: list[MoonRecord]):
        if not records:
            raise RuntimeError("No NASA Dial-A-Moon metadata is cached.")

        self.records = records
        self.by_time = {r.time_utc: r for r in records}
        self.subearth_lon = np.array([r.subearth_lon for r in records])
        self.subearth_lat = np.array([r.subearth_lat for r in records])
        self.subsolar_lon = np.array([r.subsolar_lon for r in records])
        self.subsolar_lat = np.array([r.subsolar_lat for r in records])
        self.distance = np.array([r.distance for r in records])

    def __len__(self) -> int:
        return len(self.records)

    @property
    def years(self) -> list[int]:
        return sorted({r.year for r in self.records})

    @classmethod
    def load(cls, paths: CachePaths) -> "Catalog":
        """
        Load all cached annual JSON files into memory.

        No NASA network access occurs here.
        """

        records: list[MoonRecord] = []

        for path in sorted(paths.metadata.glob("mooninfo_*.json")):
            try:
                year = int(path.stem.split("_")[1])
            except (IndexError, ValueError):
                continue

            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            for index, item in enumerate(data):
                try:
                    records.append(_record_from_json(year, index, item))
                except (KeyError, TypeError, ValueError) as exc:
                    log.warning(
                        "skipping malformed %s record %s: %s",
                        path.name,
                        index,
                        exc,
                    )

        return cls(records)

    def exact(self, utc_dt: datetime) -> Optional[MoonRecord]:
        """
        Return the NASA record for the nearest whole hour, if published.

        Rounds half up, matching NASA's own Dial-A-Moon API (21:30 maps
        to the 22:00 frame).
        """

        hour = utc_dt.astimezone(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
        if utc_dt - hour >= timedelta(minutes=30):
            hour += timedelta(hours=1)
        return self.by_time.get(hour)
