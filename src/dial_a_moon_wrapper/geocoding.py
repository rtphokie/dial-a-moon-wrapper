"""
Place-name lookup ("Raleigh, NC" -> latitude/longitude).

Uses OpenStreetMap's Nominatim service. Per its usage policy
(https://operations.osmfoundation.org/policies/nominatim/) requests carry
an identifying User-Agent, are limited to one per second, and results are
cached in ``metadata/geocode.json`` so a place is only looked up once.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass

from . import catalog as cat
from .paths import CachePaths

log = logging.getLogger(__name__)

NOMINATIM_URL = os.environ.get(
    "DIALAMOON_GEOCODER_URL", "https://nominatim.openstreetmap.org/search"
)
MIN_INTERVAL = 1.0

_COORDINATES = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*[,\s]\s*([+-]?\d+(?:\.\d+)?)\s*$"
)

_lock = threading.Lock()
_last_request = 0.0


@dataclass(frozen=True)
class Place:
    query: str
    name: str
    latitude: float
    longitude: float
    source: str


def _normalize(query: str) -> str:
    return " ".join(query.casefold().replace(",", ", ").split())


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """Return (lat, lon) if ``text`` is a "lat, lon" pair, else None."""

    match = _COORDINATES.match(text)
    if match is None:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"Coordinates out of range: {text!r}")
    return lat, lon


def _read_cache(paths: CachePaths) -> dict:
    try:
        return json.loads(paths.geocode_cache.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_cache(paths: CachePaths, cache: dict) -> None:
    paths.metadata.mkdir(parents=True, exist_ok=True)
    temporary = paths.geocode_cache.with_suffix(".tmp")
    temporary.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(paths.geocode_cache)


def _nominatim(query: str) -> list[dict]:
    global _last_request

    with _lock:
        wait = _last_request + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            response = cat.SESSION.get(
                NOMINATIM_URL,
                params={"q": query, "format": "jsonv2", "limit": 1},
                headers={"Accept-Language": "en"},
                timeout=cat.REQUEST_TIMEOUT,
            )
        finally:
            _last_request = time.monotonic()

    response.raise_for_status()
    return response.json()


def geocode(query: str, paths: CachePaths) -> Place:
    """
    Resolve a place name or a "lat, lon" string to coordinates.

    Raises LookupError when the place cannot be found.
    """

    coordinates = parse_coordinates(query)
    if coordinates is not None:
        return Place(query, query.strip(), *coordinates, source="coordinates")

    key = _normalize(query)
    if not key:
        raise LookupError("Empty place name")

    cache = _read_cache(paths)
    if key in cache:
        return Place(**{**cache[key], "query": query, "source": "cache"})

    log.info("Geocoding %r via Nominatim", query)
    results = _nominatim(query)
    if not results:
        raise LookupError(f"Could not find a location named {query!r}")

    best = results[0]
    place = Place(
        query=query,
        name=best.get("display_name", query),
        latitude=float(best["lat"]),
        longitude=float(best["lon"]),
        source="nominatim",
    )
    cache[key] = asdict(place)
    _write_cache(paths, cache)
    return place
