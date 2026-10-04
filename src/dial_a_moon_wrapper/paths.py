"""
Cache directory resolution.

Order of precedence:

1. An explicit ``cache_dir`` argument (``--cache-dir`` on the CLI).
2. The ``DIALAMOON_CACHE`` environment variable.
3. ``/var/data/dialamoon`` when ``/var/data`` exists and is writable.
4. ``<system temp dir>/dialamoon`` (``tempfile.gettempdir()``), which
   resolves to ``/tmp`` or ``$TMPDIR`` on Linux/macOS and ``%TEMP%`` on
   Windows. Every script using this package on the machine shares it.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

SHARED_DATA_DIR = Path("/var/data")
CACHE_ENV_VAR = "DIALAMOON_CACHE"
CACHE_SUBDIR = "dialamoon"


def default_cache_root() -> Path:
    env = os.environ.get(CACHE_ENV_VAR)
    if env:
        return Path(env).expanduser()

    if SHARED_DATA_DIR.is_dir() and os.access(SHARED_DATA_DIR, os.W_OK):
        return SHARED_DATA_DIR / CACHE_SUBDIR

    return Path(tempfile.gettempdir()) / CACHE_SUBDIR


@dataclass(frozen=True)
class CachePaths:
    root: Path

    @classmethod
    def resolve(cls, cache_dir: str | os.PathLike | None = None) -> "CachePaths":
        root = Path(cache_dir).expanduser() if cache_dir else default_cache_root()
        return cls(root=root)

    @property
    def metadata(self) -> Path:
        return self.root / "metadata"

    @property
    def images(self) -> Path:
        return self.root / "images"

    @property
    def results(self) -> Path:
        return self.root / "results"

    @property
    def frame_manifest(self) -> Path:
        return self.metadata / "frames.json"

    @property
    def geocode_cache(self) -> Path:
        return self.metadata / "geocode.json"

    def metadata_file(self, year: int) -> Path:
        return self.metadata / f"mooninfo_{year}.json"

    def ensure(self) -> "CachePaths":
        for directory in (self.metadata, self.images, self.results):
            directory.mkdir(parents=True, exist_ok=True)
        return self
