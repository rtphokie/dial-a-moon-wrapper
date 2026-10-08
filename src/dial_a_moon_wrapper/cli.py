"""Command-line interface: ``dial-a-moon`` / ``python -m dial_a_moon_wrapper``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import timedelta
from typing import Optional, Sequence

from . import catalog as cat
from ._version import __version__
from .core import render_moon
from .paths import CachePaths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dial-a-moon",
        description="Generate an observer-oriented NASA Dial-A-Moon Moon image.",
    )
    parser.add_argument(
        "--datetime",
        help="Local date/time at the observer: 'YYYY-MM-DD HH:MM' or ISO 8601. "
        "Defaults to now.",
    )
    parser.add_argument(
        "place",
        nargs="?",
        help="Place name, e.g. 'Raleigh, NC' or 'Paris, France' "
        "(alternative to --latitude/--longitude).",
    )
    parser.add_argument("--latitude", type=float, help="Degrees, north positive.")
    parser.add_argument("--longitude", type=float, help="Degrees, east positive.")
    parser.add_argument(
        "--elevation", type=float, default=0.0, help="Observer elevation in meters."
    )
    parser.add_argument("--timezone", help="Optional IANA timezone override.")
    parser.add_argument(
        "--orientation",
        choices=("zenith", "north"),
        default="zenith",
        help="Put the observer's zenith (default) or celestial north at the top.",
    )
    parser.add_argument(
        "--resolution",
        type=int,
        choices=cat.RESOLUTIONS,
        default=730,
        help="NASA frame width: 730 (default; 730 px output), or 1920/3840/5760 "
        "(1080/2160/3240 px output). Falls back to the largest smaller size "
        "the year has.",
    )
    parser.add_argument("--output", "-o", help="Path for the rotated image.")
    parser.add_argument(
        "--cache-dir", help="Cache root (default: $DIALAMOON_CACHE, "
        "/var/data/dialamoon, or the system temp dir)."
    )
    parser.add_argument(
        "--ephemeris-file",
        help="Path to an existing copy of JPL's de421.bsp (default: found in or "
        "downloaded to the cache).",
    )
    parser.add_argument(
        "--cache-ttl",
        type=float,
        default=14,
        metavar="DAYS",
        help="Delete cached NASA images and generated images unused for this "
        "many days (default 14; 0 disables).",
    )
    parser.add_argument(
        "--no-image",
        action="store_true",
        help="Select the frame and compute geometry only; download nothing.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the full result as JSON."
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Update the local annual JSON cache first.",
    )
    parser.add_argument(
        "--force-bootstrap",
        action="store_true",
        help="Redownload cached annual JSON files.",
    )
    parser.add_argument(
        "--bootstrap-only",
        action="store_true",
        help="Update the cache and exit (no location needed).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    paths = CachePaths.resolve(args.cache_dir).ensure()

    if args.bootstrap or args.force_bootstrap or args.bootstrap_only:
        cat.bootstrap_metadata(paths, force=args.force_bootstrap)
        if args.bootstrap_only:
            print(f"Cache: {paths.root}")
            return 0

    has_coordinates = args.latitude is not None or args.longitude is not None
    if args.place and has_coordinates:
        parser.error("give a place name or --latitude/--longitude, not both")
    if not args.place and (args.latitude is None or args.longitude is None):
        parser.error("a place name or both --latitude and --longitude are required")

    try:
        result = render_moon(
            args.datetime,
            args.latitude,
            args.longitude,
            place=args.place,
            elevation=args.elevation,
            timezone_name=args.timezone,
            orientation=args.orientation,
            resolution=args.resolution,
            output=args.output,
            cache_dir=paths.root,
            ephemeris_file=args.ephemeris_file,
            cache_ttl=timedelta(days=args.cache_ttl) if args.cache_ttl > 0 else None,
            download_image=not args.no_image,
        )
    except Exception as exc:  # surface a clean message on the CLI
        if args.verbose:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    src = result.source
    obs = result.observer
    if result.place:
        print(f"Place:    {result.place.name} ({result.latitude:.2f}, {result.longitude:.2f})")
    print(f"Local:    {result.local_datetime.isoformat()}")
    print(f"UTC:      {result.utc_datetime.isoformat()}")
    print(f"Zone:     {result.timezone}")
    print(f"Status:   {result.status}")
    print(f"Source:   {src.year} frame {src.frame_number} ({src.time_utc.isoformat()})")
    phase = result.phase
    print(f"Phase:    {phase.name}, {phase.illumination:.1f}% illuminated")
    for label, event in (("Previous", phase.previous), ("Next", phase.next)):
        if event:
            when = result.local_time(event.utc_datetime)
            print(f"{label + ':':<10}{event.name}, {when:%Y-%m-%d %H:%M %Z}")
    print(f"Moon:     alt {obs.altitude:.1f} deg, az {obs.azimuth:.1f} deg")
    print(f"Rotation: {result.rotation_degrees:+.1f} deg ({result.orientation} up)")
    if result.image:
        print(f"Image:    {result.image} (NASA {result.resolution} frame)")
    for note in result.notes:
        print(f"Note:     {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
