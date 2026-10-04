# dial-a-moon-wrapper

Observer-oriented images of the Moon for **any date and any place on Earth**
(given as a place name like `"Raleigh, NC"` or as coordinates),
built on NASA's [Scientific Visualization Studio Dial-A-Moon](https://svs.gsfc.nasa.gov/gallery/moonphase/)
renderings.

NASA publishes one 730×730 frame per hour for each year from 2011 onward,
along with metadata for each frame: phase, libration, distance and position
angle. Each frame shows the Moon from Earth's center with celestial north up.
This package adds two things:

1. **Local orientation.** The frame is rotated so it matches what an observer
   at the given latitude/longitude actually sees, with the zenith at the top of
   the image (or celestial north, if you prefer).
2. **Coverage outside NASA's years.** For a date NASA hasn't rendered (before
   2011, or years after the current one), the lunar geometry is computed
   locally with [Skyfield](https://rhodesmill.org/skyfield/). The cached NASA
   frame whose sub-Earth point, sub-solar point and distance are closest is
   then used, rotated to the computed position angle. Note: the NASA SVS team
   generally publishes the following year's images and metadata each November.
   Beginning in October the package checks for them (at most once a day) and
   updates the local cache automatically.

## Installation

```bash
pip install dial-a-moon-wrapper
```

Requires Python 3.11+. Dependencies: `numpy`, `pillow`, `requests`,
`skyfield`, `timezonefinder` (plus `tzdata` on Windows).

## Command line

```bash
# Moon from Raleigh, NC at 9:30 PM local time
dial-a-moon "Raleigh, NC" --datetime "2026-10-04 21:30"

# Same thing with coordinates
dial-a-moon --datetime "2026-10-04 21:30" --latitude 35.78 --longitude -78.64

# Right now, write the image to a specific file
dial-a-moon --latitude 51.48 --longitude 0.0 -o moon.jpg

# A date NASA hasn't rendered, celestial north up, full JSON result
dial-a-moon --datetime "2031-03-08 03:00" --latitude -33.87 --longitude 151.21 \
    --orientation north --json

# Populate or refresh the metadata cache only
dial-a-moon --bootstrap-only -v
```

Give either `PLACE` or both `--latitude` and `--longitude`; everything else is optional.

| Option                      | Purpose                                                                                                                              |
|-----------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| `--datetime`                | Local wall-clock time at the observer (`YYYY-MM-DD HH:MM` or ISO 8601). Defaults to now. An ISO string with an offset is used as-is. |
| `PLACE`                     | Observer's city and state or province such as `"Raleigh, NC"`, `"Paris, France"` or `"Mauna Kea"`. A `"lat, lon"` string also works. |
| `--latitude`, `--longitude` | Degrees, north and east positive. Use these *or* a place name.                                                                       |
| `--elevation`               | Meters above sea level (default 0).                                                                                                  |
| `--timezone`                | IANA zone override. (default determined from coordinates).                                                                           |
| `--orientation`             | `zenith` (default) or `north`.                                                                                                       |
| `-o`, `--output`            | Image path. Defaults to `<cache>/results/`.                                                                                          |
| `--cache-dir`               | Cache root (optional)                                                                                                                |
| `--ephemeris-file`          | Path to an existing copy of JPL's `de421.bsp`. Optional; it's otherwise downloaded once (~17 MB) and cached.                         |
| `--no-image`                | Select the frame and compute geometry only. Downloads no image.                                                                      |
| `--json`                    | Print the full result as JSON.                                                                                                       |
| `--bootstrap`               | Refresh NASA metadata (`--force-bootstrap` re-downloads it; `--bootstrap-only` refreshes and exits).                                 |
| `-v`                        | Log progress to stderr.                                                                                                              |

Example output:

```
Local:    2031-03-08T03:00:00-05:00
UTC:      2031-03-08T08:00:00+00:00
Zone:     America/New_York
Status:   estimated
Source:   2013 frame 1321 (2013-02-25T00:00:00+00:00)
Phase:    99.0% illuminated
Moon:     alt 33.4 deg, az 247.6 deg
Rotation: -46.6 deg (zenith up)
Image:    /var/data/dialamoon/results/20310308T080000Z_+35.7800_-78.6400_zenith.jpg
```

## Library

```python
from datetime import datetime, timezone
from dial_a_moon_wrapper import render_moon

result = render_moon("2026-10-04 21:30", place="Raleigh, NC")
# or: render_moon("2026-10-04 21:30", latitude=35.78, longitude=-78.64)

result.image  # Path to the rotated JPEG
result.status  # "official" (exact NASA frame) or "estimated"
result.source  # MoonRecord: NASA frame metadata (phase, age, libration, ...)
result.place  # Place(name, latitude, longitude, ...) when a place was given
result.observer  # altitude, azimuth, parallactic_angle
result.above_horizon  # bool
result.rotation_degrees  # counter-clockwise rotation applied to NASA's frame
result.to_dict()  # JSON-serializable summary (also written next to the image)

# Aware datetimes are used as-is; naive ones are local time at the observer.
render_moon(datetime(2040, 1, 1, 6, tzinfo=timezone.utc), 64.15, -21.94,
            orientation="north", output="reykjavik.jpg")

# Geometry only, no download
render_moon(None, 35.78, -78.64, download_image=False)
```

`render_moon` keyword arguments mirror the CLI: `place`, `elevation`, `timezone_name`,
`orientation`, `output`, `cache_dir`, `ephemeris_file`, `download_image`,
`auto_bootstrap`, `check_updates`, `write_json`.

## Place names

Place names are resolved with OpenStreetMap's
[Nominatim](https://nominatim.org/) service, and the top match is used. The
CLI prints the resolved name (e.g. *Raleigh, Wake County, North Carolina,
United States*), so you can see which place was picked. Make ambiguous names
more specific: `"Portland, OR"` rather than `"Portland"`.

Results are cached in `metadata/geocode.json`, so each place is looked up only
once. Lookups follow Nominatim's [usage
policy](https://operations.osmfoundation.org/policies/nominatim/): at most one
request per second, with an identifying User-Agent. For heavy use, point
`DIALAMOON_GEOCODER_URL` at your own Nominatim instance. Elevation isn't
looked up; pass `--elevation` if it matters.

You can also geocode on its own:

```python
from dial_a_moon_wrapper import CachePaths, geocode

geocode("Tokyo, Japan", CachePaths.resolve())  # Place(..., latitude=35.68, longitude=139.76)
```

The first run downloads about 16 annual JSON files (roughly 2 MB each) and the
JPL DE421 ephemeris (`de421.bsp`, ~17 MB), the only ephemeris used.
An existing copy is reused if it sits in the cache directory or the directory above it,
or if you point `--ephemeris-file` / `DIALAMOON_EPHEMERIS` at it.
Each NASA image frame is downloaded the first time it's needed and cached for
reuse, and the script begins looking for the following year's metadata file in October.

## How it works

**Frame selection.** A request is rounded to the nearest hour, the same way
NASA's own Dial-A-Moon API rounds. If a cached annual file covers that hour,
the NASA frame is used directly. Otherwise the sub-Earth and sub-solar
selenographic coordinates, distance and position angle are computed for the
exact instant (Skyfield + Meeus, *Astronomical Algorithms* ch. 53). The
cached frame minimizing a weighted distance is then chosen:

| Quantity                       | Scale       |
|--------------------------------|-------------|
| sub-Earth longitude / latitude | 5° / 3°     |
| sub-solar longitude / latitude | 10° / 0.75° |
| distance                       | 15,000 km   |

The locally computed geometry agrees with NASA's published values to within
about 0.04° in libration, 1 km in distance and 0.2° in position angle
(`tests/test_geometry.py`).

**Rotation.** NASA frames have celestial north up and east to the left. The
image is rotated counter-clockwise by

```
(target position angle − source position angle) − parallactic angle
```

The first term matters only for estimated frames. The parallactic angle term
is dropped for `--orientation north`.

## Limitations

- NASA frames are geocentric. Topocentric (diurnal) libration, up to about 1°,
  is not reflected in the imagery.
- The disk size of a substituted frame reflects the source frame's distance.
  That distance is part of the match, so it's usually close.
- Dates must fall within DE421's coverage, 1899-07-29 to 2053-10-07 (a day
  inside the file's limits). Requests outside it raise a `ValueError`.
- Lunar eclipses are not handled specially. Requests resolve to the nearest
  hourly frame, not NASA's minute-by-minute eclipse renderings.
- New years are found through NASA's Dial-A-Moon API and the SVS page layout.
  If NASA changes either, a new year may not be picked up automatically; add
  its visualization ID to `ANNUAL_VISUALIZATIONS` in `catalog.py`.

## Development

```bash
uv sync                      # or: pip install -e . pytest
pytest                       # offline unit tests + ephemeris accuracy tests
pytest --run-network         # also check live NASA SVS URLs
```

## License

MIT. See [LICENSE](LICENSE). This covers the code only; NASA imagery and
OpenStreetMap data carry their own terms, below.

## Credits

Geocoding: © OpenStreetMap contributors, via Nominatim (ODbL).

Imagery and metadata: NASA's Scientific Visualization Studio, *Moon Phase and
Libration* (visualizer Ernie Wright, USRA; planetary scientist Noah Petro,
NASA/GSFC; producer James Tralie, eMITS).

Lunar surface data: NASA/Lunar Reconnaissance Orbiter (LRO). The renderings
use the LROC Wide Angle Camera natural-color mosaic (NASA/GSFC/Arizona State
University) and Lunar Orbiter Laser Altimeter (LOLA) elevation data
(NASA/GSFC).

Ephemeris: JPL DE421 planetary and lunar ephemeris, NASA/Jet Propulsion
Laboratory (Folkner, Williams & Boggs, *The Planetary and Lunar Ephemeris
DE 421*, IPN Progress Report 42-178, 2009). NASA's Dial-A-Moon renderings are
computed from DE421 as well. Positions are computed with
[Skyfield](https://rhodesmill.org/skyfield/) by Brandon Rhodes.

NASA imagery is generally not subject to copyright in the United States. See
[NASA's media usage
guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/).
