"""
Observer-oriented NASA Dial-A-Moon image generation.

``render_moon`` is the public entry point. For a requested instant it

1. uses the exact NASA frame when the hour is covered by a cached annual
   file ("official"), otherwise
2. computes the lunar geometry for that instant locally and picks the
   cached NASA frame with the closest geometry ("estimated"), then
3. rotates the frame so it matches what the observer sees, with the
   zenith (or celestial north) at the top of the image.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional, Union
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image

from . import catalog as cat
from .catalog import Catalog, MoonRecord
from .geocoding import Place, geocode
from .geometry import (
    ObserverGeometry,
    TargetGeometry,
    compute_observer_geometry,
    compute_target_geometry,
)
from .paths import CachePaths

log = logging.getLogger(__name__)

Orientation = Literal["zenith", "north"]
DateLike = Union[datetime, str, None]

# Approximate natural scale of each quantity's effect on the lunar
# appearance. Typical ranges:
#
# sub-Earth longitude       ~ +/- 8 deg
# sub-Earth latitude        ~ +/- 7 deg
# subsolar longitude        0-360 deg
# subsolar latitude         ~ +/- 1.5 deg
# distance                  ~ 356,000-407,000 km
#
# Position angle is deliberately excluded because the source image is
# rotated to the target position angle afterwards.
GEOMETRY_SCALES = {
    "subearth_lon": 5.0,
    "subearth_lat": 3.0,
    "subsolar_lon": 10.0,
    "subsolar_lat": 0.75,
    "distance": 15000.0,
}


@dataclass
class MoonResult:
    local_datetime: datetime
    utc_datetime: datetime
    latitude: float
    longitude: float
    elevation: float
    timezone: str
    timezone_source: str
    status: Literal["official", "estimated"]
    source: MoonRecord
    target: TargetGeometry
    observer: ObserverGeometry
    orientation: Orientation
    rotation_degrees: float
    match_score: float
    place: Optional[Place] = None
    image_url: Optional[str] = None
    source_image: Optional[Path] = None
    image: Optional[Path] = None
    result_json: Optional[Path] = None
    notes: list[str] = field(default_factory=list)

    @property
    def above_horizon(self) -> bool:
        return self.observer.altitude > 0.0

    def to_dict(self) -> dict:
        record = self.source
        return {
            "request": {
                "local_datetime": self.local_datetime.isoformat(),
                "utc_datetime": self.utc_datetime.isoformat(),
                "latitude": self.latitude,
                "longitude": self.longitude,
                "elevation_m": self.elevation,
                "place": self.place.name if self.place else None,
                "timezone": self.timezone,
                "timezone_source": self.timezone_source,
                "orientation": self.orientation,
            },
            "status": self.status,
            "source": {
                "year": record.year,
                "record_index": record.index,
                "frame": record.frame_number,
                "utc_time": record.time_utc.isoformat(),
                "phase": record.phase,
                "age": record.age,
                "diameter_arcsec": record.diameter,
                "distance_km": record.distance,
                "j2000_ra_hours": record.ra,
                "j2000_dec_degrees": record.dec,
                "subsolar_longitude": record.subsolar_lon,
                "subsolar_latitude": record.subsolar_lat,
                "subearth_longitude": record.subearth_lon,
                "subearth_latitude": record.subearth_lat,
                "position_angle": record.posangle,
                "match_score": self.match_score,
            },
            "target": asdict(self.target),
            "observer": {
                **asdict(self.observer),
                "above_horizon": self.above_horizon,
            },
            "rotation_degrees": self.rotation_degrees,
            "files": {
                "image_url": self.image_url,
                "source_image": _str(self.source_image),
                "image": _str(self.image),
                "result_json": _str(self.result_json),
            },
            "notes": self.notes,
        }


def _str(path: Optional[Path]) -> Optional[str]:
    return str(path) if path is not None else None


@lru_cache(maxsize=1)
def _timezone_finder():
    from timezonefinder import TimezoneFinder

    return TimezoneFinder()


def detect_timezone(
    latitude: float,
    longitude: float,
    override: Optional[str],
) -> tuple[str, str]:
    if override:
        ZoneInfo(override)
        return override, "user"

    timezone_name = _timezone_finder().timezone_at(lat=latitude, lng=longitude)

    if timezone_name is None:
        raise RuntimeError(
            "Could not determine timezone from latitude/longitude. "
            "Use --timezone to specify an IANA timezone."
        )

    return timezone_name, "timezonefinder"


def parse_local_datetime(
    value: str,
    timezone_name: str,
) -> tuple[datetime, datetime]:
    """
    Interpret ``value`` as wall-clock time in ``timezone_name``.

    Accepts ``YYYY-MM-DD HH:MM`` or any ISO 8601 string. An ISO string
    carrying its own offset is honored as-is.
    """

    try:
        naive = datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        naive = datetime.fromisoformat(value)

    return resolve_datetime(naive, timezone_name)


def resolve_datetime(
    value: datetime,
    timezone_name: str,
) -> tuple[datetime, datetime]:
    local_zone = ZoneInfo(timezone_name)

    if value.tzinfo is None:
        local_dt = value.replace(tzinfo=local_zone)
    else:
        local_dt = value.astimezone(local_zone)

    return local_dt, local_dt.astimezone(timezone.utc)


def circular_difference(a, b):
    """
    Smallest angular difference in degrees. Works on scalars or arrays.
    """

    return np.abs((np.asarray(a) - b + 180.0) % 360.0 - 180.0)


def geometry_scores(target: TargetGeometry, catalog: Catalog) -> np.ndarray:
    """
    Weighted lunar-geometry distance from ``target`` to every record.

    Longitudes are circular.
    """

    s = GEOMETRY_SCALES
    return np.sqrt(
        (circular_difference(catalog.subearth_lon, target.subearth_lon) / s["subearth_lon"]) ** 2
        + ((catalog.subearth_lat - target.subearth_lat) / s["subearth_lat"]) ** 2
        + (circular_difference(catalog.subsolar_lon, target.subsolar_lon) / s["subsolar_lon"]) ** 2
        + ((catalog.subsolar_lat - target.subsolar_lat) / s["subsolar_lat"]) ** 2
        + ((catalog.distance - target.distance) / s["distance"]) ** 2
    )


def find_best_historical_frame(
    target: TargetGeometry,
    catalog: Catalog,
) -> tuple[MoonRecord, float]:
    scores = geometry_scores(target, catalog)
    best = int(np.argmin(scores))
    return catalog.records[best], float(scores[best])


def rotation_angle(
    target_posangle: float,
    source_posangle: float,
    parallactic_angle: float,
    orientation: Orientation = "zenith",
) -> float:
    """
    Counter-clockwise rotation (PIL convention) to apply to a NASA frame.

    NASA frames have celestial north up and east to the left, with the
    lunar axis at the source frame's position angle. The image is first
    turned so the axis sits at the target position angle (a no-op for
    official frames), then, for ``"zenith"``, by the parallactic angle
    so the observer's zenith is up.
    """

    angle = target_posangle - source_posangle
    if orientation == "zenith":
        angle -= parallactic_angle
    elif orientation != "north":
        raise ValueError(f"Unknown orientation: {orientation!r}")
    return float((angle + 180.0) % 360.0 - 180.0)


def download_file(url: str, destination: Path) -> None:
    if destination.exists():
        return

    log.info("Downloading %s", url)

    response = cat.SESSION.get(url, timeout=cat.REQUEST_TIMEOUT, stream=True)
    response.raise_for_status()

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")

    with temporary.open("wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)

    temporary.replace(destination)


def rotate_image(
    source_path: Path,
    destination_path: Path,
    angle_degrees: float,
) -> None:
    """
    Rotate the NASA Moon image counter-clockwise around its center.

    The disk is inset within the frame, so ``expand=False`` never clips
    the Moon; uncovered corners are filled black to match the sky.
    """

    with Image.open(source_path) as image:
        rotated = image.convert("RGB").rotate(
            angle_degrees,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=(0, 0, 0),
        )

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    rotated.save(destination_path, quality=95)


_catalog_cache: dict[tuple, Catalog] = {}


def load_catalog(paths: CachePaths) -> Catalog:
    """Load the catalog, reusing it while the cached files are unchanged."""

    key = (paths.root,) + tuple(
        (p.name, p.stat().st_mtime_ns)
        for p in sorted(paths.metadata.glob("mooninfo_*.json"))
    )
    if key not in _catalog_cache:
        _catalog_cache.clear()
        _catalog_cache[key] = Catalog.load(paths)
    return _catalog_cache[key]


def render_moon(
    when: DateLike = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    *,
    place: Optional[str] = None,
    elevation: float = 0.0,
    timezone_name: Optional[str] = None,
    orientation: Orientation = "zenith",
    output: Optional[Union[str, os.PathLike]] = None,
    cache_dir: Optional[Union[str, os.PathLike]] = None,
    ephemeris: Optional[str] = None,
    download_image: bool = True,
    auto_bootstrap: bool = True,
    write_json: bool = True,
) -> MoonResult:
    """
    Produce an observer-oriented image of the Moon.

    Args:
        when: Requested instant. ``None`` means now. A naive datetime or a
            ``"YYYY-MM-DD HH:MM"`` / ISO string is local wall-clock time
            at the observer; an aware datetime is used as-is.
        latitude, longitude: Observer position in degrees (east positive).
        place: Alternatively, a place name such as ``"Raleigh, NC"`` or
            ``"Paris, France"`` (looked up via OpenStreetMap and cached),
            or a ``"lat, lon"`` string.
        elevation: Observer elevation in meters.
        timezone_name: IANA zone overriding the one looked up from the
            coordinates.
        orientation: ``"zenith"`` puts the observer's zenith at the top
            of the image, ``"north"`` keeps celestial north up.
        output: Where to write the rotated image. Defaults to the
            cache's ``results/`` directory.
        cache_dir: Cache root. See :mod:`dial_a_moon_wrapper.paths`.
        ephemeris: Skyfield ephemeris name or path (default de421.bsp).
        download_image: If False, only select the frame and compute the
            geometry; no image is fetched or written.
        auto_bootstrap: Download NASA's annual metadata if none is cached.
        write_json: Write a JSON sidecar next to the image.
    """

    paths = CachePaths.resolve(cache_dir).ensure()

    resolved_place: Optional[Place] = None
    if place is not None:
        if latitude is not None or longitude is not None:
            raise ValueError("Give either place or latitude/longitude, not both")
        resolved_place = geocode(place, paths)
        latitude, longitude = resolved_place.latitude, resolved_place.longitude
    elif latitude is None or longitude is None:
        raise ValueError("A place or both latitude and longitude are required")

    if auto_bootstrap and not cat.has_metadata(paths):
        cat.bootstrap_metadata(paths)

    if isinstance(when, datetime) and when.tzinfo is not None:
        try:
            tz_name, tz_source = detect_timezone(latitude, longitude, timezone_name)
        except RuntimeError:
            tz_name, tz_source = "UTC", "fallback"
    else:
        tz_name, tz_source = detect_timezone(latitude, longitude, timezone_name)

    if when is None:
        local_dt, utc_dt = resolve_datetime(datetime.now(timezone.utc), tz_name)
    elif isinstance(when, str):
        local_dt, utc_dt = parse_local_datetime(when, tz_name)
    else:
        local_dt, utc_dt = resolve_datetime(when, tz_name)

    catalog = load_catalog(paths)
    notes: list[str] = []

    exact = catalog.exact(utc_dt)
    target = compute_target_geometry(utc_dt, paths.root, ephemeris)

    if exact is not None:
        source, score, status = exact, 0.0, "official"
        # Rotate relative to NASA's own position angle for this frame.
        target = TargetGeometry(**{**asdict(target), "posangle": exact.posangle})
    else:
        source, score = find_best_historical_frame(target, catalog)
        status = "estimated"
        notes.append(
            "NASA has not published an annual Dial-A-Moon rendering for "
            "the requested time. The source frame is a NASA rendering "
            "selected by lunar geometry and rotated to the computed "
            "position angle."
        )

    log.info("Source: %s frame %s/%s", status, source.year, source.frame_number)

    observer = compute_observer_geometry(
        utc_dt, latitude, longitude, elevation, paths.root, ephemeris
    )
    if observer.altitude <= 0.0:
        notes.append("The Moon is below the observer's horizon.")

    rotation = rotation_angle(
        target.posangle,
        source.posangle,
        observer.parallactic_angle,
        orientation,
    )

    result = MoonResult(
        local_datetime=local_dt,
        utc_datetime=utc_dt,
        latitude=latitude,
        longitude=longitude,
        elevation=elevation,
        timezone=tz_name,
        timezone_source=tz_source,
        status=status,
        source=source,
        target=target,
        observer=observer,
        orientation=orientation,
        rotation_degrees=rotation,
        match_score=score,
        place=resolved_place,
        notes=notes,
    )

    if not download_image:
        return result

    result.image_url = cat.image_url(paths, source)
    result.source_image = (
        paths.images / str(source.year) / f"moon.{source.frame_number:04d}.jpg"
    )
    download_file(result.image_url, result.source_image)

    if output is None:
        output = paths.results / (
            f"{utc_dt:%Y%m%dT%H%M%SZ}"
            f"_{latitude:+.4f}_{longitude:+.4f}_{orientation}.jpg"
        )
    result.image = Path(output)
    rotate_image(result.source_image, result.image, rotation)

    if write_json:
        result.result_json = result.image.with_suffix(".json")
        result.result_json.write_text(
            json.dumps(result.to_dict(), indent=2), encoding="utf-8"
        )

    return result
