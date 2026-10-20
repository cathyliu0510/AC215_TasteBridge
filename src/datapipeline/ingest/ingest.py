"""Ingest stage: download the raw Goodreads files into data/raw/.

Owner: Cathy Liu. First stage of the pipeline (ingest -> preprocess -> embed / evaluation).

What it does
------------
1. Downloads the five UCSD Goodreads files the pipeline needs (two genre metadata
   files, two genre interaction files, and the author table for author names).
2. In sample mode (INGEST_SAMPLE_LINES > 0) it streams each *interaction* file and
   keeps only its first N lines, so a demo run needs ~0.5 GB instead of several GB.
   Metadata and author files are always downloaded in full: preprocess needs every
   book to map editions to works.
3. Writes data/raw/manifest.json: URL, size, sha256 and line cap of every file.
   This is the "which raw data did we use" record that preprocess copies into its
   own manifest.

Files are written to "<name>.part" first and renamed at the end, so an interrupted
download never looks complete. A file already present with the same line cap is
skipped, which makes reruns cheap.

The Goodreads data is for academic use only and must not be redistributed:
data/ is git-ignored and versioned with DVC in a private bucket.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import logging
import os
import shutil
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("ingest")

DEFAULT_BASE_URL = "https://mcauleylab.ucsd.edu/public_datasets/gdrive/goodreads"


@dataclass(frozen=True)
class RawFile:
    """One raw input: local file name, path under the base URL, and whether to sample it."""

    name: str
    remote_path: str
    sampled: bool  # True only for the (very large) interaction files


# Local names are short and stable; preprocess reads exactly these names.
RAW_FILES: tuple[RawFile, ...] = (
    RawFile("books_fantasy.json.gz", "byGenre/goodreads_books_fantasy_paranormal.json.gz", False),
    RawFile("books_mystery.json.gz", "byGenre/goodreads_books_mystery_thriller_crime.json.gz", False),
    RawFile("inter_fantasy.json.gz", "byGenre/goodreads_interactions_fantasy_paranormal.json.gz", True),
    RawFile("inter_mystery.json.gz", "byGenre/goodreads_interactions_mystery_thriller_crime.json.gz", True),
    RawFile("authors.json.gz", "goodreads_book_authors.json.gz", False),
)

CHUNK_BYTES = 1 << 20  # 1 MB reads keep memory flat for multi-GB files


@dataclass(frozen=True)
class Settings:
    raw_dir: Path
    base_url: str
    sample_lines: int  # 0 = full files
    force: bool        # re-download even if the file exists

    @classmethod
    def from_env(cls) -> "Settings":
        raw = os.getenv("INGEST_SAMPLE_LINES", "0").strip() or "0"
        if not raw.isdigit():
            raise ValueError(f"INGEST_SAMPLE_LINES must be a whole number >= 0, got {raw!r}")
        return cls(
            raw_dir=Path(os.getenv("RAW_DIR", "/data/raw")),
            base_url=os.getenv("INGEST_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            sample_lines=int(raw),
            force=os.getenv("INGEST_FORCE", "0") == "1",
        )


def sha256_file(path: Path) -> str:
    """Hash in 1 MB blocks so multi-GB files never load into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def _open_url(url: str):
    """Open http(s):// or file:// URLs with the standard library (no extra dependency).

    file:// lets tests and offline demos point the stage at a local folder.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "tastebridge-ingest/0.1"})
    return urllib.request.urlopen(request, timeout=120)


def download_full(url: str, dest: Path) -> None:
    """Copy the remote file byte for byte (it stays gzip-compressed)."""
    with _open_url(url) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out, CHUNK_BYTES)


def download_head(url: str, dest: Path, max_lines: int) -> int:
    """Stream-decompress the remote gzip and keep only its first max_lines lines.

    Reading stops as soon as the cap is reached, so only a small prefix of a
    multi-GB file is ever transferred. Returns the number of lines written.
    """
    written = 0
    with _open_url(url) as response, gzip.GzipFile(fileobj=response) as source, gzip.open(
        dest, "wb"
    ) as out:
        for line in source:
            out.write(line)
            written += 1
            if written >= max_lines:
                break
    return written


def _previous_entry(manifest_path: Path, name: str) -> dict | None:
    """Manifest entry from an earlier run, used to decide whether a file can be reused."""
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))["files"].get(name)
    except (json.JSONDecodeError, KeyError, AttributeError):
        return None


def fetch_one(spec: RawFile, settings: Settings, manifest_path: Path) -> dict:
    """Download one file (or reuse it) and return its manifest entry."""
    dest = settings.raw_dir / spec.name
    url = f"{settings.base_url}/{spec.remote_path}"
    line_cap = settings.sample_lines if spec.sampled else 0

    previous = _previous_entry(manifest_path, spec.name)
    if (
        not settings.force
        and dest.is_file()
        and previous is not None
        and previous.get("line_cap", 0) == line_cap
        and previous.get("sha256") == sha256_file(dest)
    ):
        log.info("skip %s (already downloaded, line_cap=%d)", spec.name, line_cap)
        return previous

    part = dest.with_name(dest.name + ".part")
    part.unlink(missing_ok=True)
    if line_cap:
        log.info("download %s (first %d lines) from %s", spec.name, line_cap, url)
        lines = download_head(url, part, line_cap)
    else:
        log.info("download %s (full file) from %s", spec.name, url)
        download_full(url, part)
        lines = None  # not counted for full files: it would mean decompressing GBs again
    part.replace(dest)  # atomic rename: dest is either complete or absent

    entry = {
        "url": url,
        "bytes": dest.stat().st_size,
        "sha256": sha256_file(dest),
        "line_cap": line_cap,
        "lines": lines,
        "downloaded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    log.info("  %s: %.1f MB, sha256 %s", spec.name, entry["bytes"] / 1e6, entry["sha256"][:12])
    return entry


def run(settings: Settings) -> dict:
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = settings.raw_dir / "manifest.json"
    files = {spec.name: fetch_one(spec, settings, manifest_path) for spec in RAW_FILES}
    manifest = {
        "stage": "ingest",
        "source": "UCSD Goodreads Book Graph (Wan & McAuley 2018); academic use only, no redistribution",
        "base_url": settings.base_url,
        "mode": "sample" if settings.sample_lines else "full",
        "sample_lines": settings.sample_lines,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "files": files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("wrote %s (%s mode)", manifest_path, manifest["mode"])
    return manifest


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run(Settings.from_env())
    except ValueError as exc:  # bad settings: clear message, no traceback
        log.error("%s", exc)
        return 1
    except OSError as exc:  # network or disk problem
        log.error("download failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
