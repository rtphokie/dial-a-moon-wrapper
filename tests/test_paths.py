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
