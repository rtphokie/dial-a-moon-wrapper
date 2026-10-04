"""
Lunar geometry computed locally with Skyfield.

NASA's annual files only cover the years NASA has published. To pick a
stand-in frame for any other date we need the same quantities NASA
tabulates (sub-Earth point, sub-solar point, distance, position angle)
for the requested instant. Those are computed here from a JPL
ephemeris plus the optical libration formulas of Meeus, *Astronomical
Algorithms* (2nd ed.), chapter 53. Physical libration (< 0.04 deg) is
ignored, which is far below what is visible in a 730 px frame.

The observer-dependent quantities (altitude, azimuth, parallactic
angle) used to rotate the image are also computed here.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

DEFAULT_EPHEMERIS = "de421.bsp"

# Inclination of the mean lunar equator to the ecliptic (Meeus 53).
_INCLINATION = math.radians(1.54242)


@dataclass(frozen=True)
class TargetGeometry:
    """Geocentric lunar geometry, in the same units as NASA's JSON."""

    subearth_lon: float
    subearth_lat: float
    subsolar_lon: float
    subsolar_lat: float
    distance: float
    posangle: float


@dataclass(frozen=True)
class ObserverGeometry:
    """Topocentric view of the Moon for one observer."""

    altitude: float
    azimuth: float
    parallactic_angle: float


def _wrap180(degrees: float) -> float:
    return (degrees + 180.0) % 360.0 - 180.0


@lru_cache(maxsize=4)
def _load(ephemeris_dir: str, ephemeris_name: str):
    from skyfield.api import Loader

    directory = Path(ephemeris_dir)

    # Reuse an ephemeris sitting next to the cache (e.g. /var/data/de421.bsp)
    # rather than downloading a second copy.
    if (
        not (directory / ephemeris_name).exists()
        and (directory.parent / ephemeris_name).exists()
    ):
        directory = directory.parent

    loader = Loader(str(directory), verbose=False)
    return loader.timescale(), loader(ephemeris_name)


def load_ephemeris(cache_root: Path, ephemeris: str | None = None):
    """
    Return (timescale, ephemeris).

    ``ephemeris`` may be a file name (downloaded into ``cache_root`` on
    first use) or a path to an existing .bsp file. The
    ``DIALAMOON_EPHEMERIS`` environment variable is used when it is not
    given.
    """

    ephemeris = ephemeris or os.environ.get(
        "DIALAMOON_EPHEMERIS", DEFAULT_EPHEMERIS
    )
    path = Path(ephemeris).expanduser()

    if path.parent != Path(".") or path.is_absolute():
        return _load(str(path.parent.resolve()), path.name)

    return _load(str(cache_root), ephemeris)


def _selenographic(
    lam: float,
    beta: float,
    dpsi: float,
    node: float,
    arg_lat: float,
) -> tuple[float, float]:
    """
    Optical libration (Meeus 53.1) for a direction with ecliptic
    longitude ``lam`` and latitude ``beta`` (radians, of date).

    Returns selenographic (longitude, latitude) in degrees of the point
    on the Moon facing that direction.
    """

    w = lam - dpsi - node
    a = math.atan2(
        math.sin(w) * math.cos(beta) * math.cos(_INCLINATION)
        - math.sin(beta) * math.sin(_INCLINATION),
        math.cos(w) * math.cos(beta),
    )
    lon = _wrap180(math.degrees(a - arg_lat))
    lat = math.degrees(
        math.asin(
            -math.sin(w) * math.cos(beta) * math.sin(_INCLINATION)
            - math.sin(beta) * math.cos(_INCLINATION)
        )
    )
    return lon, lat


def compute_target_geometry(
    utc_dt: datetime,
    cache_root: Path,
    ephemeris: str | None = None,
) -> TargetGeometry:
    from skyfield.framelib import ecliptic_frame
    from skyfield.nutationlib import iau2000b_radians

    ts, eph = load_ephemeris(cache_root, ephemeris)
    t = ts.from_datetime(utc_dt)
    earth, moon, sun = eph["earth"], eph["moon"], eph["sun"]

    moon_app = earth.at(t).observe(moon).apparent()
    sun_app = earth.at(t).observe(sun).apparent()

    m_lat, m_lon, m_dist = moon_app.frame_latlon(ecliptic_frame)
    s_lat, s_lon, s_dist = sun_app.frame_latlon(ecliptic_frame)

    lam, beta = float(m_lon.radians), float(m_lat.radians)
    lam0 = float(s_lon.radians)
    delta_km = float(m_dist.km)
    r_km = float(s_dist.km)

    tt = (t.tt - 2451545.0) / 36525.0
    node = math.radians(
        (
            125.0445479
            - 1934.1362891 * tt
            + 0.0020754 * tt**2
            + tt**3 / 467441.0
            - tt**4 / 60616000.0
        )
        % 360.0
    )
    arg_lat = math.radians(
        (
            93.2720950
            + 483202.0175233 * tt
            - 0.0036539 * tt**2
            - tt**3 / 3526000.0
            + tt**4 / 863310000.0
        )
        % 360.0
    )
    dpsi, deps = (float(v) for v in iau2000b_radians(t))

    subearth_lon, subearth_lat = _selenographic(
        lam, beta, dpsi, node, arg_lat
    )

    # Heliocentric direction of the Moon (Meeus 53, "selenographic
    # position of the Sun").
    ratio = delta_km / r_km
    lam_h = (
        lam0
        + math.pi
        + ratio * math.cos(beta) * math.sin(lam0 - lam)
    )
    beta_h = ratio * beta
    subsolar_lon, subsolar_lat = _selenographic(
        lam_h, beta_h, dpsi, node, arg_lat
    )

    # Position angle of the Moon's axis (Meeus 53, without physical
    # libration terms).
    ra, _dec, _ = moon_app.radec(epoch=t)
    eps = math.radians(23.4392911) + deps  # adequate for 1900-2100
    v = node + dpsi
    x = math.sin(_INCLINATION) * math.sin(v)
    y = (
        math.sin(_INCLINATION) * math.cos(v) * math.cos(eps)
        - math.cos(_INCLINATION) * math.sin(eps)
    )
    omega = math.atan2(x, y)
    posangle = math.degrees(
        math.asin(
            math.hypot(x, y)
            * math.cos(float(ra.radians) - omega)
            / math.cos(math.radians(subearth_lat))
        )
    )

    return TargetGeometry(
        subearth_lon=subearth_lon,
        subearth_lat=subearth_lat,
        subsolar_lon=subsolar_lon,
        subsolar_lat=subsolar_lat,
        distance=float(delta_km),
        posangle=posangle,
    )


def parallactic_angle(
    hour_angle_deg: float,
    dec_deg: float,
    latitude_deg: float,
) -> float:
    """
    Parallactic angle q in degrees (Meeus 14.1): the position angle of
    the zenith measured from celestial north through east.
    """

    h = math.radians(hour_angle_deg)
    d = math.radians(dec_deg)
    phi = math.radians(latitude_deg)
    return math.degrees(
        math.atan2(
            math.sin(h),
            math.tan(phi) * math.cos(d) - math.sin(d) * math.cos(h),
        )
    )


def compute_observer_geometry(
    utc_dt: datetime,
    latitude: float,
    longitude: float,
    elevation: float,
    cache_root: Path,
    ephemeris: str | None = None,
) -> ObserverGeometry:
    from skyfield.api import wgs84

    ts, eph = load_ephemeris(cache_root, ephemeris)
    t = ts.from_datetime(utc_dt)
    site = eph["earth"] + wgs84.latlon(
        latitude, longitude, elevation_m=elevation
    )

    apparent = site.at(t).observe(eph["moon"]).apparent()
    alt, az, _ = apparent.altaz()
    ha, dec, _ = apparent.hadec()

    return ObserverGeometry(
        altitude=float(alt.degrees),
        azimuth=float(az.degrees),
        parallactic_angle=parallactic_angle(
            float(ha.hours) * 15.0, float(dec.degrees), latitude
        ),
    )
