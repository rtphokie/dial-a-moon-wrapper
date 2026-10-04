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

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SHARED_DATA_DIR = Path("/var/data")
CACHE_ENV_VAR = "DIALAMOON_CACHE"
CACHE_SUBDIR = "dialamoon"

# NASA frames and generated images not used for this long are deleted.
DEFAULT_CACHE_TTL = timedelta(days=14)
PRUNE_INTERVAL = timedelta(days=1)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


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
    def visualizations(self) -> Path:
        return self.metadata / "visualizations.json"

    @property
    def update_check(self) -> Path:
        return self.metadata / "update_check.json"

    @property
    def prune_check(self) -> Path:
        return self.metadata / "prune_check.json"

    @property
    def geocode_cache(self) -> Path:
        return self.metadata / "geocode.json"

    def metadata_file(self, year: int) -> Path:
        return self.metadata / f"mooninfo_{year}.json"

    def ensure(self) -> "CachePaths":
        for directory in (self.metadata, self.images, self.results):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def prune_cache(
    paths: CachePaths,
    ttl: timedelta = DEFAULT_CACHE_TTL,
    now: datetime | None = None,
) -> int:
    """
    Delete image files, i.e. NASA frames (``images/``) and generated
    images (``results/``), not used within ``ttl``, at most once per day.
    Returns the number of files removed.

    "Used" is the later of a file's access and modification times; the
    package also refreshes a frame's modification time whenever it
    reuses it, since many filesystems don't update access times. Only
    image files are removed: JSON results, annual metadata, the
    place-name cache and the ephemeris are never pruned.
    """

    now = now or datetime.now(timezone.utc)
    try:
        last = datetime.fromisoformat(
            json.loads(paths.prune_check.read_text(encoding="utf-8"))["last_prune"]
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        last = None
    if last is not None and now - last < PRUNE_INTERVAL:
        return 0

    paths.metadata.mkdir(parents=True, exist_ok=True)
    paths.prune_check.write_text(
        json.dumps({"last_prune": now.isoformat()}), encoding="utf-8"
    )

    cutoff = (now - ttl).timestamp()
    removed = 0
    for top in (paths.images, paths.results):
        if not top.is_dir():
            continue
        for path in sorted(top.rglob("*"), reverse=True):  # files before their dirs
            try:
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                    st = path.stat()
                    if max(st.st_atime, st.st_mtime) < cutoff:
                        path.unlink()
                        removed += 1
                elif path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
            except OSError:  # removed concurrently, or not ours to delete
                continue

    if removed:
        log.info(
            "Removed %d cached images unused for %g days",
            removed,
            ttl.total_seconds() / 86400,
        )
    return removed
