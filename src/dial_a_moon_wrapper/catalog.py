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
    try:
        return json.loads(paths.frame_manifest.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_manifest(paths: CachePaths, manifest: dict[str, str]) -> None:
    temporary = paths.frame_manifest.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    temporary.replace(paths.frame_manifest)


def frames_url(paths: CachePaths, year: int) -> str:
    """
    Return the 730x730 frame directory for ``year``, discovering and
    caching it in ``metadata/frames.json`` on first use.
    """

    manifest = _read_manifest(paths)
    key = str(year)
    if key not in manifest:
        manifest[key] = discover_frames_url(ANNUAL_VISUALIZATIONS[year])
        paths.metadata.mkdir(parents=True, exist_ok=True)
        _write_manifest(paths, manifest)
    return manifest[key]


def image_url(paths: CachePaths, record: MoonRecord) -> str:
    return urljoin(
        frames_url(paths, record.year),
        f"moon.{record.frame_number:04d}.jpg",
    )


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

    visualization_id = ANNUAL_VISUALIZATIONS.get(year)

    if visualization_id is None:
        raise RuntimeError(f"No NASA visualization ID is known for {year}")

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

    # NASA historically publishes the following year's visualization
    # in November. Start checking in October.
    if now.month >= 10:
        next_year = current_year + 1

        if next_year in ANNUAL_VISUALIZATIONS:
            try:
                download_annual_json(paths, next_year, force=force)
            except Exception as exc:
                log.info("%s: not yet available: %s", next_year, exc)


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
