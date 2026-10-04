# dial-a-moon-wrapper

Images of the Moon as seen from a given place and time on Earth, built on NASA's
[Dial-A-Moon](https://svs.gsfc.nasa.gov/gallery/moonphase/) renderings.

- **Oriented for the observer:** NASA's frames are rotated so the zenith is up
  (or celestial north).
- **Beyond NASA's years:** dates NASA hasn't rendered use the NASA frame with
  the closest lunar geometry. Each new year's data is picked up automatically once NASA
  publishes it (usually November).
- **Square output, disk centered:** black background at 730 px (JPEG), or
  transparent at high resolution (PNG), matching NASA's frames.

## Install

```bash
pip install dial-a-moon-wrapper
```

Requires Python 3.11+.

## Command line

```bash
dial-a-moon "Raleigh, NC" --datetime "2026-10-04 21:30"
dial-a-moon --latitude 35.78 --longitude -78.64 --resolution 5760 -o moon.png
```

Give a place name or `--latitude`/`--longitude`; everything else is optional.

| Option | |
|---|---|
| `--datetime` | Local time at the observer, `YYYY-MM-DD HH:MM` or ISO 8601, between 1899-07-29 and 2053-10-07 (the range of JPL's DE421 ephemeris). Default: now. |
| `--elevation` | Meters (default 0). |
| `--timezone` | IANA zone; default from the location. |
| `--orientation` | `zenith` (default) or `north`. |
| `--resolution` | `730` (default, 730 px JPEG), or `1920`/`3840`/`5760` (1080/2160/3240 px PNG). Years without the size use the next largest. |
| `-o`, `--output` | Image path. Default: `<cache>/results/<orientation>/<resolution>/`. |
| `--cache-dir` | Cache location. |
| `--cache-ttl` | Days before unused cached images are deleted (default 14; 0 keeps them). |
| `--ephemeris-file` | Existing `de421.bsp` to use instead of downloading it. |
| `--no-image` | Geometry only. |
| `--json` | Print the result as JSON. |
| `--bootstrap` | Refresh NASA metadata. |
| `-v` | Verbose. |

## Library

```python
from dial_a_moon_wrapper import render_moon

result = render_moon("2026-10-04 21:30", place="Raleigh, NC")
result.image     # path to the image
result.status    # "official" (NASA frame for that hour) or "estimated"
result.to_dict() # full details
```

Keyword arguments match the CLI options.

## Notes

- The first run downloads NASA's metadata (~30 MB) and JPL's DE421 ephemeris
  (~17 MB). Images are cached as they're used and deleted after 14 days unused.
- Place names are looked up once via OpenStreetMap and cached.
- NASA's frames are geocentric and hourly (no minute-by-minute eclipse frames).

## Development

```bash
pytest                 # offline tests
pytest --run-network   # plus live NASA checks
```

## License and credits

Code: MIT ([LICENSE](LICENSE)).

- Imagery and metadata: NASA Scientific Visualization Studio, *Moon Phase and
  Libration* (Ernie Wright, Noah Petro, James Tralie).
- Lunar surface data: NASA/Lunar Reconnaissance Orbiter (LROC WAC mosaic,
  NASA/GSFC/Arizona State University; LOLA, NASA/GSFC).
- Ephemeris: JPL DE421, NASA/JPL (Folkner et al. 2009), via
  [Skyfield](https://rhodesmill.org/skyfield/).
- Geocoding: © OpenStreetMap contributors (ODbL), via Nominatim.

NASA imagery is generally not subject to U.S. copyright; see NASA's
[media guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/).
