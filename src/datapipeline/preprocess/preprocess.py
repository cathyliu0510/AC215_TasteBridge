"""Preprocess stage: raw Goodreads files -> work-level catalogue + interactions.

Owner: Cathy Liu. Second pipeline stage (ingest -> preprocess -> embed / evaluation / train).

Input  (data/raw/, written by ingest)
    books_fantasy.json.gz, books_mystery.json.gz   edition-level metadata
    inter_fantasy.json.gz, inter_mystery.json.gz   user-edition interactions
    authors.json.gz                                author_id -> name
    manifest.json                                  ingest's record of the raw files

Output (data/processed/)
    books.parquet         one row per work: the catalogue (contract below)
    interactions.parquet  one row per (user, work): user_id, work_id, rating, is_read
    manifest.json         data_version, parameters, counts, quality summary, input hashes

Steps (the proposal's "Data Sources" section)
    1. Map every edition (book_id) to its work (work_id). Editions of one book become
       one item, so a reader's two editions never leak across the train/test split.
    2. Count likes (rating >= 4) per work over both genres; keep the MAX_WORKS most
       liked works as the catalogue (proposal cap: 5,000).
    3. Keep interactions on catalogue works, one row per (user, work) with the best
       rating; keep users with >= MIN_USER_LIKES likes; cap the total at
       MAX_INTERACTIONS by sampling whole users with a fixed seed (cap: 500,000).
    4. Build the book table: title/author/year from the most-rated edition, shelves
       summed over all editions, then YiTong's add_quality_flags() cleans the
       description and shelves and flags missing/short descriptions.
    5. Write files to a temp folder, hash them into data_version, then swap the folder
       into place, so data/processed/ is always a complete, consistent run.

The user split (80/10/10) is NOT done here: the evaluation package splits users
itself with a fixed seed, so every model sees the same split.

Output contract (consumed by three teammates' stages)
    books.parquet  work_id (str), title, author, author_id, year (nullable int),
                   description, description_issue, has_description,   <- embed (YiTong)
                   shelves (list[str]),                               <- embed + backend reasons
                   genre ("fantasy" | "mystery" | "both"),            <- embed genre filter
                   genres (list[str]),                                <- evaluation pairs (Anhad)
                   n_editions, n_likes, n_ratings
    interactions.parquet  user_id (str), work_id (str), rating (0-5), is_read (bool)
                                                                      <- evaluation + training
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from array import array
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import orjson
import pandas as pd

from quality import add_quality_flags

log = logging.getLogger("preprocess")

GENRES = ("fantasy", "mystery")       # source genre subsets, in a fixed order
LIKE_THRESHOLD = 4                    # proposal: a "like" is a rating >= 4
MIN_TEST_LIKES = 15                   # proposal: a test reader needs >= 15 likes
CODE_VERSION_FILES = ("preprocess.py", "quality.py")


# --------------------------------------------------------------------- settings
@dataclass(frozen=True)
class Settings:
    raw_dir: Path
    out_dir: Path
    max_works: int          # catalogue size cap
    max_interactions: int   # total (user, work) rows cap
    min_user_likes: int     # drop users too sparse to learn from
    seed: int               # fixes the user sampling
    log_every: int          # progress log interval, in lines

    @classmethod
    def from_env(cls) -> "Settings":
        def whole(name: str, default: int, minimum: int) -> int:
            raw = os.getenv(name, str(default)).strip()
            if not raw.isdigit() or int(raw) < minimum:
                raise ValueError(f"{name} must be a whole number >= {minimum}, got {raw!r}")
            return int(raw)

        return cls(
            raw_dir=Path(os.getenv("RAW_DIR", "/data/raw")),
            out_dir=Path(os.getenv("PROCESSED_DIR", "/data/processed")),
            max_works=whole("PREPROCESS_MAX_WORKS", 5000, 1),
            max_interactions=whole("PREPROCESS_MAX_INTERACTIONS", 500_000, 1),
            min_user_likes=whole("PREPROCESS_MIN_USER_LIKES", 5, 1),
            seed=whole("PREPROCESS_SEED", 42, 0),
            log_every=whole("PREPROCESS_LOG_EVERY", 5_000_000, 1),
        )


# ---------------------------------------------------------------- raw reading
def iter_jsonl_gz(path: Path, log_every: int = 5_000_000):
    """Yield one dict per line of a .json.gz file, streaming (never loads the file).

    orjson parses ~3x faster than the json module, which matters for ~80M lines.
    Broken lines are counted and skipped rather than stopping a long run.
    """
    bad = 0
    with gzip.open(path, "rb") as handle:
        for n, line in enumerate(handle, 1):
            try:
                yield orjson.loads(line)
            except orjson.JSONDecodeError:
                bad += 1
            if n % log_every == 0:
                log.info("  %s: %d lines read", path.name, n)
    if bad:
        log.warning("  %s: skipped %d unreadable lines", path.name, bad)


def _to_int(value: object) -> int | None:
    """Goodreads stores numbers as strings, often empty: '' -> None, '12' -> 12."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _primary_author(authors: object) -> str | None:
    """First author with an empty role (the writer), else the first listed author."""
    if not isinstance(authors, list) or not authors:
        return None
    for entry in authors:
        if isinstance(entry, dict) and not (entry.get("role") or "").strip():
            return str(entry.get("author_id") or "") or None
    first = authors[0]
    if not isinstance(first, dict):
        return None
    return str(first.get("author_id") or "") or None


# ------------------------------------------------------- step 1: edition -> work
def build_edition_map(raw_dir: Path, log_every: int) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Return {book_id: work_id} and {work_id: {genres}} from both metadata files.

    Editions without a work_id cannot be grouped and are dropped.
    """
    book_to_work: dict[str, str] = {}
    work_genres: dict[str, set[str]] = defaultdict(set)
    for genre in GENRES:
        path = raw_dir / f"books_{genre}.json.gz"
        log.info("step 1: reading %s", path.name)
        for rec in iter_jsonl_gz(path, log_every):
            book_id, work_id = str(rec.get("book_id") or ""), str(rec.get("work_id") or "")
            if book_id and work_id:
                book_to_work[book_id] = work_id
                work_genres[work_id].add(genre)
    log.info("step 1: %d editions -> %d works", len(book_to_work), len(work_genres))
    return book_to_work, work_genres


# ------------------------------------------------ step 2: catalogue (top works)
def count_work_likes(raw_dir: Path, book_to_work: dict[str, str], log_every: int) -> tuple[Counter, int]:
    """Likes per work over both interaction files (pass 1 of 2 over interactions).

    Counts every like row; the same reader liking two editions counts twice here,
    which only affects which works enter the catalogue, not the final data.
    """
    likes: Counter = Counter()
    lines = 0
    for genre in GENRES:
        path = raw_dir / f"inter_{genre}.json.gz"
        log.info("step 2: counting likes in %s", path.name)
        for rec in iter_jsonl_gz(path, log_every):
            lines += 1
            if (_to_int(rec.get("rating")) or 0) >= LIKE_THRESHOLD:
                work = book_to_work.get(str(rec.get("book_id")))
                if work is not None:
                    likes[work] += 1
    return likes, lines


def select_catalogue(likes: Counter, max_works: int) -> list[str]:
    """Most-liked works first; ties broken by work_id so the result is deterministic."""
    ranked = sorted(likes.items(), key=lambda kv: (-kv[1], kv[0]))
    return [work for work, _ in ranked[:max_works]]


# ------------------------------------------- step 3: interactions on catalogue
def collect_interactions(
    raw_dir: Path, book_to_work: dict[str, str], catalogue: list[str], log_every: int
) -> tuple[pd.DataFrame, list[str]]:
    """Pass 2 of 2: one row per (user, work) with the best rating and any 'read' flag.

    Memory: the full files hold ~80M lines, and tens of millions can touch catalogue
    works. Instead of a dict of string tuples (several GB), every row is stored as
    small integers in compact arrays (~9 bytes/row): a user code, a work code, the
    rating and the read flag. Strings come back only after filtering and the cap.

    Rows that are neither read nor rated (a bare 'to-read' shelf) carry no taste
    signal and are dropped here.

    Returns (frame with integer user/work codes, user_id strings indexed by code).
    """
    work_code = {work: i for i, work in enumerate(catalogue)}
    user_code: dict[str, int] = {}
    users, works = array("i"), array("h" if len(catalogue) < 32_000 else "i")
    ratings, reads = array("b"), array("b")
    for genre in GENRES:
        path = raw_dir / f"inter_{genre}.json.gz"
        log.info("step 3: collecting catalogue interactions from %s", path.name)
        for rec in iter_jsonl_gz(path, log_every):
            work = book_to_work.get(str(rec.get("book_id")))
            w = work_code.get(work) if work is not None else None
            if w is None:
                continue
            rating = _to_int(rec.get("rating")) or 0
            is_read = bool(rec.get("is_read"))
            if rating == 0 and not is_read:
                continue
            u = user_code.setdefault(str(rec.get("user_id")), len(user_code))
            users.append(u)
            works.append(w)
            ratings.append(max(0, min(5, rating)))
            reads.append(1 if is_read else 0)
    log.info("step 3: %d raw catalogue rows from %d users", len(users), len(user_code))
    frame = pd.DataFrame(
        {
            "user": np.frombuffer(users, dtype=np.int32),
            "work": np.frombuffer(works, dtype=np.int16 if works.typecode == "h" else np.int32),
            "rating": np.frombuffer(ratings, dtype=np.int8),
            "is_read": np.frombuffer(reads, dtype=np.int8),
        }
    )
    # Several editions of one work -> one row: best rating, read if any edition was read.
    frame = frame.groupby(["user", "work"], sort=True, as_index=False).agg(
        rating=("rating", "max"), is_read=("is_read", "max")
    )
    user_names = list(user_code)  # position == code, because codes were handed out in order
    return frame, user_names


def decode_interactions(frame: pd.DataFrame, user_names: list[str], catalogue: list[str]) -> pd.DataFrame:
    """Integer codes -> the string contract columns (only done on the capped, small frame)."""
    names = np.asarray(user_names, dtype=object)
    works = np.asarray(catalogue, dtype=object)
    out = pd.DataFrame(
        {
            "user_id": pd.Series(names[frame["user"].to_numpy()], dtype="string"),
            "work_id": pd.Series(works[frame["work"].to_numpy()], dtype="string"),
            "rating": frame["rating"].to_numpy(dtype=np.int8),
            "is_read": frame["is_read"].to_numpy().astype(bool),
        }
    )
    return out.sort_values(["user_id", "work_id"], kind="stable").reset_index(drop=True)


def filter_and_cap(frame: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """Keep users with enough likes, then sample whole users down to the row cap.

    Works on the integer-coded frame from collect_interactions ("user" column).
    Sampling users (not rows) keeps each kept reader's full history, which the
    evaluation needs (>= 15 likes per test reader). The seed makes it repeatable.
    """
    user_likes = frame.loc[frame["rating"] >= LIKE_THRESHOLD].groupby("user").size()
    keep = user_likes.index[user_likes >= settings.min_user_likes]
    frame = frame[frame["user"].isin(keep)]

    rows_per_user = frame.groupby("user").size().sort_index()  # sorted -> deterministic
    if rows_per_user.sum() > settings.max_interactions:
        rng = np.random.default_rng(settings.seed)
        order = rows_per_user.index[rng.permutation(len(rows_per_user))]
        cumulative = rows_per_user.loc[order].cumsum()
        chosen = cumulative.index[cumulative <= settings.max_interactions]
        frame = frame[frame["user"].isin(chosen)]
    return frame.reset_index(drop=True)


# ------------------------------------------------------- step 4: book table
def collect_editions(raw_dir: Path, works: set[str], log_every: int) -> dict[str, list[dict]]:
    """All editions of the catalogue works, keeping only the fields we use."""
    editions: dict[str, list[dict]] = defaultdict(list)
    for genre in GENRES:
        path = raw_dir / f"books_{genre}.json.gz"
        log.info("step 4: reading catalogue editions from %s", path.name)
        for rec in iter_jsonl_gz(path, log_every):
            work = str(rec.get("work_id") or "")
            if work in works:
                editions[work].append(
                    {
                        "book_id": str(rec.get("book_id") or ""),
                        "title": (rec.get("title") or "").strip(),
                        "author_id": _primary_author(rec.get("authors")),
                        "year": _to_int(rec.get("publication_year")),
                        "ratings_count": _to_int(rec.get("ratings_count")) or 0,
                        "description": rec.get("description") or "",
                        "popular_shelves": rec.get("popular_shelves") or [],
                    }
                )
    return editions


def load_author_names(raw_dir: Path, needed: set[str], log_every: int) -> dict[str, str]:
    names: dict[str, str] = {}
    for rec in iter_jsonl_gz(raw_dir / "authors.json.gz", log_every):
        author_id = str(rec.get("author_id") or "")
        if author_id in needed:
            names[author_id] = (rec.get("name") or "").strip()
    return names


def summarize_work(work_id: str, editions: list[dict]) -> dict:
    """Collapse a work's editions into one catalogue row.

    The most-rated edition supplies title and author (usually the English original).
    The year is the earliest plausible edition year. Shelves are concatenated over
    editions; add_quality_flags() later sums duplicate shelf counts.
    """
    # Duplicate editions can appear in both genre files: dedupe by book_id first.
    unique = list({e["book_id"]: e for e in editions}.values())
    main = sorted(unique, key=lambda e: (-e["ratings_count"], e["book_id"]))[0]
    years = [e["year"] for e in unique if e["year"] and 1000 <= e["year"] <= 2018]
    description = main["description"].strip() or max(
        (e["description"] for e in unique), key=lambda d: len(d.strip()), default=""
    )
    shelves = [shelf for e in unique for shelf in e["popular_shelves"]]
    return {
        "work_id": work_id,
        "title": main["title"],
        "author_id": main["author_id"],
        "year": min(years) if years else None,
        "description": description,
        "popular_shelves": shelves,
        "n_editions": len(unique),
        "n_ratings": sum(e["ratings_count"] for e in unique),
    }


def build_books(
    raw_dir: Path,
    interactions: pd.DataFrame,
    work_genres: dict[str, set[str]],
    log_every: int,
) -> tuple[pd.DataFrame, dict]:
    works = set(interactions["work_id"].unique())
    editions = collect_editions(raw_dir, works, log_every)
    rows = [summarize_work(work, editions[work]) for work in sorted(works) if editions.get(work)]
    books = pd.DataFrame(rows)

    names = load_author_names(raw_dir, set(books["author_id"].dropna()), log_every)
    books["author"] = books["author_id"].map(names).fillna("Unknown author")

    # Genre labels: 'both' when the work appears in both genre subsets.
    genres = books["work_id"].map(lambda w: sorted(work_genres.get(w, set())))
    books["genres"] = genres
    books["genre"] = genres.map(lambda g: "both" if len(g) > 1 else (g[0] if g else "unknown"))

    likes = interactions.loc[interactions["rating"] >= LIKE_THRESHOLD].groupby("work_id").size()
    books["n_likes"] = books["work_id"].map(likes).fillna(0).astype("int64")
    books["year"] = books["year"].astype("Int64")

    # YiTong's quality step: cleans description + shelves, adds has_description and
    # description_issue, returns the summary we store in manifest.json["quality"].
    books, quality = add_quality_flags(books, shelves_col="popular_shelves")
    books = books.drop(columns=["popular_shelves"])

    # Catalogue order = most liked first (the backend shows search hits in this order).
    books = books.sort_values(["n_likes", "work_id"], ascending=[False, True], kind="stable")
    columns = [
        "work_id", "title", "author", "author_id", "year", "description",
        "description_issue", "has_description", "shelves", "genre", "genres",
        "n_editions", "n_likes", "n_ratings",
    ]
    return books[columns].reset_index(drop=True), quality


# ------------------------------------------------------ step 5: write + version
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def code_version(here: Path) -> str:
    """git commit when available; inside Docker (no git) a hash of the source files."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=here, capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    digest = hashlib.sha256()
    for name in CODE_VERSION_FILES:
        digest.update((here / name).read_bytes())
    return f"src-sha256:{digest.hexdigest()[:12]}"


def write_outputs(settings: Settings, books: pd.DataFrame, interactions: pd.DataFrame, manifest: dict) -> dict:
    """Write to <out>.tmp, compute data_version, then swap the folder into place."""
    tmp = settings.out_dir.with_name(settings.out_dir.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)

    books.to_parquet(tmp / "books.parquet", index=False)
    interactions.to_parquet(tmp / "interactions.parquet", index=False)

    hashes = {name: sha256_file(tmp / name) for name in ("books.parquet", "interactions.parquet")}
    # data_version: short hash of the output files + the settings that produced them.
    fingerprint = json.dumps({"files": hashes, "params": manifest["params"]}, sort_keys=True)
    manifest["data_version"] = "gr-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:12]
    manifest["files"] = hashes
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    old = settings.out_dir.with_name(settings.out_dir.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    if settings.out_dir.exists():
        settings.out_dir.rename(old)
    tmp.rename(settings.out_dir)
    shutil.rmtree(old, ignore_errors=True)
    return manifest


def run(settings: Settings) -> dict:
    started = dt.datetime.now(dt.timezone.utc)
    missing = [
        name for name in (*(f"books_{g}.json.gz" for g in GENRES),
                          *(f"inter_{g}.json.gz" for g in GENRES), "authors.json.gz")
        if not (settings.raw_dir / name).is_file()
    ]
    if missing:
        raise FileNotFoundError(
            f"missing raw file(s) in {settings.raw_dir}: {', '.join(missing)}. Run the ingest stage first."
        )

    book_to_work, work_genres = build_edition_map(settings.raw_dir, settings.log_every)
    likes, lines = count_work_likes(settings.raw_dir, book_to_work, settings.log_every)
    catalogue = select_catalogue(likes, settings.max_works)
    log.info("step 2: %d interaction lines, %d liked works -> catalogue of %d", lines, len(likes), len(catalogue))

    coded, user_names = collect_interactions(settings.raw_dir, book_to_work, catalogue, settings.log_every)
    n_before = len(coded)
    interactions = decode_interactions(filter_and_cap(coded, settings), user_names, catalogue)
    del coded, user_names  # free the large intermediate before reading book metadata
    log.info("step 3: %d (user, work) rows -> %d after user filter and cap", n_before, len(interactions))
    if interactions.empty:
        raise ValueError("no interactions left after filtering; raise INGEST_SAMPLE_LINES or lower the filters")

    books, quality = build_books(settings.raw_dir, interactions, work_genres, settings.log_every)
    interactions = interactions[interactions["work_id"].isin(set(books["work_id"]))].reset_index(drop=True)

    user_likes = interactions.loc[interactions["rating"] >= LIKE_THRESHOLD].groupby("user_id").size()
    ingest_manifest = settings.raw_dir / "manifest.json"
    manifest = {
        "stage": "preprocess",
        "created_at": started.isoformat(timespec="seconds"),
        "code_version": code_version(Path(__file__).resolve().parent),
        "params": {
            "max_works": settings.max_works,
            "max_interactions": settings.max_interactions,
            "min_user_likes": settings.min_user_likes,
            "like_threshold": LIKE_THRESHOLD,
            "seed": settings.seed,
        },
        "inputs": json.loads(ingest_manifest.read_text()) if ingest_manifest.is_file() else None,
        "counts": {
            "editions_mapped": len(book_to_work),
            "works_total": len(work_genres),
            "interaction_lines_read": lines,
            "catalogue_works": int(len(books)),
            "users": int(interactions["user_id"].nunique()),
            "interactions": int(len(interactions)),
            "likes": int((interactions["rating"] >= LIKE_THRESHOLD).sum()),
            "users_with_15_plus_likes": int((user_likes >= MIN_TEST_LIKES).sum()),
            "works_by_genre": books["genre"].value_counts().to_dict(),
        },
        "quality": quality,
    }
    manifest = write_outputs(settings, books, interactions, manifest)
    c = manifest["counts"]
    log.info(
        "done: data_version %s | %d works, %d users, %d interactions (%d likes), %d users with >=15 likes",
        manifest["data_version"], c["catalogue_works"], c["users"], c["interactions"], c["likes"],
        c["users_with_15_plus_likes"],
    )
    return manifest


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run(Settings.from_env())
    except (ValueError, FileNotFoundError) as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
