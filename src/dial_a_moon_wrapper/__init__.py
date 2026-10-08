"""
NASA Dial-A-Moon observer-oriented Moon image generator.

The lunar geometry catalog is built from NASA SVS annual Moon Phase and
Libration JSON files, cached locally. Dates NASA has published use the
exact NASA frame; any other date uses the NASA frame whose lunar
geometry best matches the computed geometry for that instant. The frame
is then rotated for the observer's location.

Library use::

    from dial_a_moon_wrapper import render_moon

    result = render_moon("2026-10-04 21:30", 35.78, -78.64)
    result = render_moon("2026-10-04 21:30", place="Raleigh, NC")
    print(result.image, result.status)

CLI use::

    dial-a-moon --datetime "2026-10-04 21:30" --latitude 35.78 --longitude -78.64
    dial-a-moon "Raleigh, NC" --datetime "2026-10-04 21:30"
"""

from ._version import __version__
from .catalog import Catalog, MoonRecord, bootstrap_metadata
from .cli import main
from .core import MoonResult, render_moon
from .geocoding import Place, geocode
from .geometry import LunarPhase, ObserverGeometry, PhaseEvent, TargetGeometry
from .paths import CachePaths, default_cache_root

__all__ = [
    "__version__",
    "CachePaths",
    "Catalog",
    "LunarPhase",
    "MoonRecord",
    "MoonResult",
    "ObserverGeometry",
    "PhaseEvent",
    "Place",
    "TargetGeometry",
    "bootstrap_metadata",
    "default_cache_root",
    "geocode",
    "main",
    "render_moon",
]
