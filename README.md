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

| 2026-12-14, 9 PM local | NASA frame (north up) | As seen by the observer |
|---|---|---|
| Raleigh, NC | ![NASA frame](https://raw.githubusercontent.com/rtphokie/dial-a-moon-wrapper/main/docs/images/raleigh_nasa.jpg) | ![Raleigh view](https://raw.githubusercontent.com/rtphokie/dial-a-moon-wrapper/main/docs/images/raleigh_observer.jpg) |
| Sydney, Australia | ![NASA frame](https://raw.githubusercontent.com/rtphokie/dial-a-moon-wrapper/main/docs/images/sydney_nasa.jpg) | ![Sydney view](https://raw.githubusercontent.com/rtphokie/dial-a-moon-wrapper/main/docs/images/sydney_observer.jpg) |

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
Coordinates, including geocoded ones, are rounded to 2 decimal places (about
1 km), and the time to the nearest minute. Finer precision doesn't visibly
change the Moon's orientation. Rounding lets repeated requests reuse the
cached image instead of generating it again.

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

`result.to_dict()` (the same JSON that `--json` prints) looks like this:

```json
{
  "request": {
    "local_datetime": "2026-10-04T21:30:00-04:00",
    "utc_datetime": "2026-10-05T01:30:00+00:00",
    "latitude": 35.78,
    "longitude": -78.64,
    "elevation_m": 0.0,
    "place": "Raleigh, Wake County, North Carolina, United States",
    "timezone": "America/New_York",
    "timezone_source": "location",
    "orientation": "zenith",
    "resolution": 730
  },
  "status": "official",
  "source": {
    "year": 2026,
    "record_index": 6650,
    "frame": 6651,
    "utc_time": "2026-10-05T02:00:00+00:00",
    "phase": 33.07,
    "age": 23.94,
    "diameter_arcsec": 1926.5,
    "distance_km": 372026.0,
    "j2000_ra_hours": 8.282,
    "j2000_dec_degrees": 22.1524,
    "subsolar_longitude": -106.934,
    "subsolar_latitude": -1.079,
    "subearth_longitude": 2.955,
    "subearth_latitude": -3.018,
    "position_angle": 11.563,
    "match_score": 0.0
  },
  "phase": {
    "name": "Waning Crescent",
    "illumination": 33.2919,
    "elongation_degrees": 289.6776,
    "previous": {
      "name": "Last Quarter",
      "local_datetime": "2026-10-03T09:25:00-04:00",
      "utc_datetime": "2026-10-03T13:25:00+00:00"
    },
    "next": {
      "name": "New Moon",
      "local_datetime": "2026-10-10T11:50:00-04:00",
      "utc_datetime": "2026-10-10T15:50:00+00:00"
    }
  },
  "target": {
    "subearth_lon": 2.9161,
    "subearth_lat": -3.0714,
    "subsolar_lon": -106.7043,
    "subsolar_lat": -1.0864,
    "distance": 371993.21,
    "posangle": 11.563
  },
  "observer": {
    "altitude": -31.5468,
    "azimuth": 14.3313,
    "parallactic_angle": -12.4506,
    "above_horizon": false
  },
  "rotation_degrees": 12.4506,
  "resolution": 730,
  "files": {
    "image_url": "https://svs.gsfc.nasa.gov/vis/a000000/a005500/a005587/frames/730x730_1x1_30p/moon.6651.jpg",
    "source_image": "<cache>/images/2026/moon.6651.jpg",
    "image": "<cache>/results/zenith/730/20261005T0130Z_+35.78_-78.64.jpg",
    "result_json": "<cache>/results/zenith/730/20261005T0130Z_+35.78_-78.64.json"
  },
  "notes": [
    "The Moon is below the observer's horizon."
  ]
}
```

`status` is `"official"` when NASA rendered that exact hour: the image is
NASA's frame for the top of the hour nearest the requested time, used as-is
apart from the rotation. It is `"estimated"` when NASA hasn't rendered that
time (years before 2011 or not yet published). The image is then NASA's frame
whose lunar geometry best matches the requested time, rotated to the correct
position angle. `match_score` is the weighted geometry difference between that
frame and the target (lower is closer; `0.0` for official frames).

`source` is the NASA frame used (its hour, phase, libration and position
angle). `phase` is computed for the exact requested time: the name, percent
illuminated, the Moon–Sun elongation, and the previous and next principal
phases (New Moon, First Quarter, Full Moon, Last Quarter) to the minute. Within
12 hours of a principal phase the Moon takes that phase's name. Otherwise it
is a Waxing/Waning Crescent or Gibbous. `target` is the computed geometry for the exact requested time;
`observer` gives the Moon's altitude/azimuth and the parallactic angle used for
`rotation_degrees`. `files` paths are `null` with `--no-image`.

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
