import os
import tempfile
from pathlib import Path

import pytest

from dial_a_moon_wrapper import paths


@pytest.fixture
def no_env(monkeypatch):
    monkeypatch.delenv(paths.CACHE_ENV_VAR, raising=False)


def test_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.CACHE_ENV_VAR, str(tmp_path / "x"))
    assert paths.default_cache_root() == tmp_path / "x"


def test_uses_var_data_when_present(monkeypatch, tmp_path, no_env):
    shared = tmp_path / "var-data"
    shared.mkdir()
    monkeypatch.setattr(paths, "SHARED_DATA_DIR", shared)
    assert paths.default_cache_root() == shared / "dialamoon"


def test_falls_back_to_temp_when_missing(monkeypatch, tmp_path, no_env):
    monkeypatch.setattr(paths, "SHARED_DATA_DIR", tmp_path / "does-not-exist")
    assert paths.default_cache_root() == Path(tempfile.gettempdir()) / "dialamoon"


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="POSIX non-root only")
def test_falls_back_to_temp_when_not_writable(monkeypatch, tmp_path, no_env):
    shared = tmp_path / "ro"
    shared.mkdir()
    shared.chmod(0o555)
    try:
        monkeypatch.setattr(paths, "SHARED_DATA_DIR", shared)
        assert paths.default_cache_root() == Path(tempfile.gettempdir()) / "dialamoon"
    finally:
        shared.chmod(0o755)


def test_explicit_cache_dir_and_layout(tmp_path):
    p = paths.CachePaths.resolve(tmp_path / "c").ensure()
    assert p.root == tmp_path / "c"
    for d in (p.metadata, p.images, p.results):
        assert d.is_dir()
    assert p.metadata_file(2024).name == "mooninfo_2024.json"
    assert p.frame_manifest.parent == p.metadata


# --- cache TTL -------------------------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402


def _aged(path, days, now):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    t = (now - timedelta(days=days)).timestamp()
    os.utime(path, (t, t))
    return path


def test_prune_removes_only_stale_images_and_results(tmp_path):
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    p = paths.CachePaths(tmp_path / "c").ensure()
    old_frame = _aged(p.images / "2013" / "moon.0001.jpg", 20, now)
    old_result = _aged(p.results / "zenith" / "730" / "a.jpg", 15, now)
    fresh_frame = _aged(p.images / "2026" / "5760" / "moon.0002.tif", 3, now)
    old_png = _aged(p.results / "north" / "5760" / "b.png", 15, now)
    metadata = _aged(p.metadata_file(2013), 400, now)
    old_json = _aged(p.results / "zenith" / "730" / "a.json", 30, now)
    old_partial = _aged(p.images / "2013" / "moon.0002.jpg.tmp", 30, now)

    assert paths.prune_cache(p, timedelta(days=14), now=now) == 3
    assert not old_frame.exists() and not old_result.exists() and not old_png.exists()
    assert fresh_frame.exists() and metadata.exists()
    assert old_json.exists() and old_partial.exists()  # only images are pruned
    assert not (p.results / "north").exists()  # emptied dirs removed
    assert p.images.is_dir() and p.results.is_dir()


def test_prune_uses_latest_of_access_and_modify_time(tmp_path):
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    p = paths.CachePaths(tmp_path / "c").ensure()
    f = _aged(p.images / "2013" / "moon.0001.jpg", 30, now)
    recent = (now - timedelta(days=1)).timestamp()
    os.utime(f, (recent, f.stat().st_mtime))  # read yesterday
    assert paths.prune_cache(p, timedelta(days=14), now=now) == 0
    assert f.exists()


def test_prune_runs_at_most_daily(tmp_path):
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    p = paths.CachePaths(tmp_path / "c").ensure()
    paths.prune_cache(p, timedelta(days=14), now=now)
    _aged(p.images / "2013" / "moon.0001.jpg", 30, now)
    assert paths.prune_cache(p, timedelta(days=14), now=now + timedelta(hours=12)) == 0
    assert paths.prune_cache(p, timedelta(days=14), now=now + timedelta(days=1)) == 1
