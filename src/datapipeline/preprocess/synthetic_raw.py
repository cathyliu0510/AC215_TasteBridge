"""Invented raw files shaped exactly like the Goodreads downloads (for tests and offline demos).

Nothing here is real Goodreads data. It mimics the raw format so preprocess can be
tested end to end without the multi-GB download:
  * editions: several book_ids per work_id, numbers stored as strings, empty strings
    for missing values, popular_shelves as [{"count": "12", "name": "to-read"}, ...]
  * some works appear in both genre files ('both'), some descriptions are missing
  * readers have a taste (mostly fantasy, mostly mystery, or mixed), so liked works
    cluster and evaluation can tell models apart

Usage (writes the five raw files + an ingest-style manifest.json):
    python synthetic_raw.py --out ../../../data/raw --works 400 --users 1500
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

FANTASY_SHELVES = ["fantasy", "epic-fantasy", "magic", "dragons", "heist", "urban-fantasy", "young-adult"]
MYSTERY_SHELVES = ["mystery", "thriller", "crime", "detective", "psychological-thriller", "suspense", "noir"]
GENERIC_SHELVES = ["to-read", "currently-reading", "favorites", "owned", "kindle", "fiction"]


def _write_jsonl_gz(path: Path, records) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for rec in records:
            handle.write(json.dumps(rec) + "\n")


def make_raw(out: Path, n_works: int = 400, n_users: int = 1500, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    out.mkdir(parents=True, exist_ok=True)

    # Works: 45% fantasy, 45% mystery, 10% in both genre files.
    kinds = rng.choice(["fantasy", "mystery", "both"], size=n_works, p=[0.45, 0.45, 0.10])
    n_authors = max(5, n_works // 4)
    authors = [{"author_id": str(9000 + a), "name": f"Author {a}", "average_rating": "4.0",
                "text_reviews_count": "1", "ratings_count": "10"} for a in range(n_authors)]

    editions = {"fantasy": [], "mystery": []}
    work_editions: dict[int, list[str]] = {}
    next_book = 100_000
    for w in range(n_works):
        work_id = str(500_000 + w)
        author = authors[int(rng.integers(n_authors))]["author_id"]
        pool = FANTASY_SHELVES if kinds[w] == "fantasy" else MYSTERY_SHELVES if kinds[w] == "mystery" \
            else FANTASY_SHELVES[:3] + MYSTERY_SHELVES[:3]
        has_desc = rng.random() > 0.1  # ~10% of works have no description at all
        ids = []
        for e in range(int(rng.integers(1, 4))):  # 1-3 editions per work
            book_id = str(next_book)
            next_book += 1
            ids.append(book_id)
            shelves = [{"count": str(int(rng.integers(5, 300))), "name": s}
                       for s in rng.choice(pool, size=4, replace=False)]
            shelves += [{"count": str(int(rng.integers(50, 900))), "name": s}
                        for s in rng.choice(GENERIC_SHELVES, size=2, replace=False)]
            rec = {
                "book_id": book_id, "work_id": work_id,
                "title": f"Invented Book {w}" + ("" if e == 0 else f" (edition {e + 1})"),
                "title_without_series": f"Invented Book {w}",
                "authors": [{"author_id": author, "role": ""}],
                "publication_year": str(int(rng.integers(1950, 2017))) if rng.random() > 0.2 else "",
                "ratings_count": str(int(rng.integers(1, 5000))),
                "description": (f"<p>Invented description for book {w}: a {kinds[w]} story with "
                                f"{pool[0]} and {pool[1]} themes.</p>") if has_desc and e == 0 else "",
                "popular_shelves": shelves, "language_code": "eng",
            }
            for genre in (["fantasy", "mystery"] if kinds[w] == "both" else [kinds[w]]):
                editions[genre].append(rec)
        work_editions[w] = ids

    # Readers: a taste decides which genre they mostly read; ~20% are mixed.
    fantasy_works = [w for w in range(n_works) if kinds[w] in ("fantasy", "both")]
    mystery_works = [w for w in range(n_works) if kinds[w] in ("mystery", "both")]
    popularity = rng.zipf(1.6, size=n_works).astype(float)  # a few very popular works
    inter = {"fantasy": [], "mystery": []}
    for u in range(n_users):
        user_id = hashlib.md5(f"user{u}".encode()).hexdigest()
        taste = rng.choice(["fantasy", "mystery", "mixed"], p=[0.4, 0.4, 0.2])
        pool = fantasy_works if taste == "fantasy" else mystery_works if taste == "mystery" \
            else fantasy_works + mystery_works
        weights = popularity[pool] / popularity[pool].sum()
        n_read = int(rng.integers(8, 45))
        for w in rng.choice(pool, size=min(n_read, len(pool)), replace=False, p=weights):
            genre = "fantasy" if w in fantasy_works and (w not in mystery_works or rng.random() < 0.5) \
                else "mystery"
            rating = int(rng.choice([0, 3, 4, 5], p=[0.15, 0.2, 0.35, 0.3]))
            inter[genre].append({
                "user_id": user_id, "book_id": str(rng.choice(work_editions[w])),
                "review_id": hashlib.md5(f"{u}-{w}".encode()).hexdigest(),
                "is_read": rating > 0 or rng.random() < 0.3, "rating": rating,
                "date_added": "Mon Jan 01 00:00:00 -0800 2017",
            })
        if u % 10 == 0:  # bare "to-read" shelf rows that preprocess must drop
            inter["fantasy"].append({"user_id": user_id, "book_id": str(rng.choice(work_editions[0])),
                                     "is_read": False, "rating": 0, "review_id": "x"})

    files = {
        "books_fantasy.json.gz": editions["fantasy"],
        "books_mystery.json.gz": editions["mystery"],
        "inter_fantasy.json.gz": inter["fantasy"],
        "inter_mystery.json.gz": inter["mystery"],
        "authors.json.gz": authors,
    }
    entries = {}
    for name, records in files.items():
        _write_jsonl_gz(out / name, records)
        entries[name] = {"url": "synthetic", "bytes": (out / name).stat().st_size,
                         "sha256": hashlib.sha256((out / name).read_bytes()).hexdigest(),
                         "line_cap": 0, "lines": len(records)}
    manifest = {"stage": "ingest", "source": "SYNTHETIC (invented data, not Goodreads)",
                "mode": "synthetic", "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "files": entries}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("/data/raw"))
    parser.add_argument("--works", type=int, default=400)
    parser.add_argument("--users", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    m = make_raw(args.out, args.works, args.users, args.seed)
    print(f"wrote synthetic raw files to {args.out}: "
          + ", ".join(f"{k} ({v['lines']} lines)" for k, v in m["files"].items()))
