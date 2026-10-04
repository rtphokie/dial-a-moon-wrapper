import json

import pytest

from dial_a_moon_wrapper import cli

from .test_core import offline  # noqa: F401  (fixture)


def test_requires_location(cache):  # neither place nor coordinates
    with pytest.raises(SystemExit):
        cli.main(["--cache-dir", str(cache.root)])


def test_json_output(offline, capsys):  # noqa: F811
    cache, _, _ = offline
    rc = cli.main([
        "--cache-dir", str(cache.root),
        "--datetime", "2020-01-02 10:00",
        "--latitude", "35.78", "--longitude", "-78.64",
        "--no-image", "--json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "official"
    assert payload["request"]["timezone"] == "America/New_York"


def test_text_output(offline, capsys):  # noqa: F811
    cache, _, _ = offline
    rc = cli.main([
        "--cache-dir", str(cache.root),
        "--datetime", "2035-05-01 22:00",
        "--latitude", "35.78", "--longitude", "-78.64",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Status:   estimated" in out and "Image:" in out


def test_bad_datetime_is_clean_error(offline, capsys):  # noqa: F811
    cache, _, _ = offline
    rc = cli.main([
        "--cache-dir", str(cache.root),
        "--datetime", "yesterday-ish",
        "--latitude", "35.78", "--longitude", "-78.64",
    ])
    assert rc == 1
    assert capsys.readouterr().err.startswith("error:")


def test_place_argument(offline, monkeypatch, capsys):  # noqa: F811
    from dial_a_moon_wrapper import core
    from dial_a_moon_wrapper.geocoding import Place

    monkeypatch.setattr(
        core, "geocode",
        lambda q, paths: Place(q, "Raleigh, North Carolina, United States", 35.78, -78.64, "cache"),
    )
    cache, _, _ = offline
    rc = cli.main(["Raleigh, NC", "--cache-dir", str(cache.root), "--datetime", "2020-01-02 10:00", "--no-image"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("Place:    Raleigh, North Carolina")


def test_place_and_coordinates_conflict(cache):
    with pytest.raises(SystemExit):
        cli.main(["Raleigh, NC", "--latitude", "1", "--cache-dir", str(cache.root)])
