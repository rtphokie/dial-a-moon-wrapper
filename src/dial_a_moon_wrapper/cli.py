"""Command-line interface: ``dial-a-moon`` / ``python -m dial_a_moon_wrapper``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
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
    parser.add_argument("--output", "-o", help="Path for the rotated image.")
    parser.add_argument(
        "--cache-dir", help="Cache root (default: $DIALAMOON_CACHE, "
        "/var/data/dialamoon, or the system temp dir)."
    )
    parser.add_argument("--ephemeris", help="Skyfield ephemeris name or .bsp path.")
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
            output=args.output,
            cache_dir=paths.root,
            ephemeris=args.ephemeris,
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
        print(f"Place:    {result.place.name} ({result.latitude:.4f}, {result.longitude:.4f})")
    print(f"Local:    {result.local_datetime.isoformat()}")
    print(f"UTC:      {result.utc_datetime.isoformat()}")
    print(f"Zone:     {result.timezone} ({result.timezone_source})")
    print(f"Status:   {result.status}")
    print(f"Source:   {src.year} frame {src.frame_number} ({src.time_utc.isoformat()})")
    print(f"Phase:    {src.phase:.1f}% illuminated")
    print(f"Moon:     alt {obs.altitude:.1f} deg, az {obs.azimuth:.1f} deg")
    print(f"Rotation: {result.rotation_degrees:+.1f} deg ({result.orientation} up)")
    if result.image:
        print(f"Image:    {result.image}")
    for note in result.notes:
        print(f"Note:     {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
