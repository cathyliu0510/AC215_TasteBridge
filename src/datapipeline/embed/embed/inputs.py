"""Load and validate data/processed/books.parquet (written by the preprocess stage)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ("work_id", "title", "author", "description", "shelves")
MAX_LISTED = 10


class InputError(Exception):
    """The input is missing or malformed; the run stops with exit code 1."""


def _preview(items: list) -> str:
    shown = ", ".join(str(item) for item in items[:MAX_LISTED])
    more = len(items) - MAX_LISTED
    return shown + (f" (+{more} more)" if more > 0 else "")


def load_books(path: Path) -> pd.DataFrame:
    path = Path(path)
    if not path.is_file():
        raise InputError(
            f"Input file not found: {path}. It is produced by the preprocess stage "
            "(src/datapipeline/preprocess)."
        )
    try:
        books = pd.read_parquet(path)
    except Exception as exc:  # pyarrow raises several types for a bad file
        raise InputError(f"Could not read {path} as parquet: {exc}") from exc

    missing = [c for c in REQUIRED_COLUMNS if c not in books.columns]
    if missing:
        raise InputError(f"{path} is missing required column(s): {', '.join(missing)}")
    if books.empty:
        raise InputError(f"{path} has zero rows")

    books = books.reset_index(drop=True)
    null_ids = int(books["work_id"].isna().sum())
    if null_ids:
        raise InputError(f"{path} has null work_id in {null_ids} row(s)")
    books["work_id"] = books["work_id"].astype(str)

    dupes = books.loc[books["work_id"].duplicated(), "work_id"].unique().tolist()
    if dupes:
        raise InputError(f"Duplicate work_id(s) in {path}: {_preview(dupes)}")

    titles = books["title"].astype("string").str.strip()
    empty = (titles.isna() | titles.eq("")).fillna(True).astype(bool)
    if empty.any():
        raise InputError(f"Empty title for work_id(s): {_preview(books.loc[empty, 'work_id'].tolist())}")

    if any(_has_raw_shelf_records(value) for value in books["shelves"]):
        raise InputError(
            f"{path}: `shelves` holds raw Goodreads shelf records (name/count). "
            "Run quality.add_quality_flags in preprocess first so shelves are cleaned lists of names."
        )
    return books


def _has_raw_shelf_records(shelves: object) -> bool:
    if shelves is None or isinstance(shelves, (str, float)):
        return False
    try:
        return any(isinstance(item, dict) for item in shelves)
    except TypeError:  # pd.NA and other non-iterables
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_upstream_version(input_path: Path) -> str | None:
    """data_version from the manifest.json next to the input, if readable."""
    manifest = Path(input_path).parent / "manifest.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("data_version")
    except (OSError, ValueError, AttributeError):
        return None
