"""Write a small books.parquet of INVENTED books (no Goodreads data).

Used by the tests, and for a container dry run before real preprocess output exists:

    uv run python scripts/make_synthetic_books.py --out ../../../data/processed/books.parquet
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

SYNTHETIC_BOOKS: list[dict] = [
    {"work_id": "syn-001", "title": "The Glass Heist", "author": "Mara Quill", "year": 2014,
     "description": "A crew of con artists plans an impossible robbery of a floating palace, "
                    "where every guard can read minds and every lie has a price.",
     "shelves": ["heist", "fantasy", "found-family"], "genre": "fantasy"},
    {"work_id": "syn-002", "title": "Ashes Over Wrenford", "author": "Tobias Vale", "year": 2009,
     "description": "A retired detective returns to her quiet village when the vicar is found "
                    "dead in the locked bell tower, and every neighbour has a secret.",
     "shelves": ["mystery", "cozy-mystery", "village"], "genre": "mystery"},
    {"work_id": "syn-003", "title": "The Lantern School", "author": "Ines Harrow", "year": 2017,
     "description": "A shy orphan discovers she can bend light and is sent to a hidden academy "
                    "for young mages, where the oldest spell in the library has gone missing.",
     "shelves": ["magic-school", "young-adult", "fantasy"], "genre": "fantasy"},
    {"work_id": "syn-004", "title": "Salt and Cipher", "author": "Dev Okafor", "year": 2012,
     "description": "A codebreaker in a port city of smugglers must decode a dead spy's letters "
                    "before a rival guild of thieves finds the treasure first.",
     "shelves": ["spies", "heist", "mystery"], "genre": "both"},
    {"work_id": "syn-005", "title": "Night Train to Kessel", "author": "R. Abernathy", "year": 2005,
     "description": "Twelve passengers, one snowbound train and a murdered diplomat: an inspector "
                    "has until dawn to unmask the killer.",
     "shelves": ["mystery", "locked-room", "trains"], "genre": "mystery"},
    {"work_id": "syn-006", "title": "Dragon Debt", "author": "Hal Penrose", "year": 2016,
     "description": "To pay off his family's debt, a farm boy signs on as a dragon's accountant "
                    "and uncovers a plot against the crown.",
     "shelves": ["dragons", "humor", "fantasy"], "genre": "fantasy"},
    {"work_id": "syn-007", "title": "Book Two", "author": "Anon Writer", "year": None,
     "description": "Book 2.", "shelves": ["fantasy", "series"], "genre": "fantasy"},
    {"work_id": "syn-008", "title": "The Quiet Orchard", "author": "Lena Morrow", "year": 2011,
     "description": None, "shelves": ["mystery", "small-town"], "genre": "mystery"},
]

# Same 40-character rule as preprocess/quality.py (all blurbs above are already clean).
for _book in SYNTHETIC_BOOKS:
    _desc = _book["description"]
    if _desc is None:
        _book["has_description"], _book["description_issue"] = False, "missing"
    elif len(_desc) < 40:
        _book["has_description"], _book["description_issue"] = False, "too_short"
    else:
        _book["has_description"], _book["description_issue"] = True, None


def synthetic_books() -> pd.DataFrame:
    books = pd.DataFrame(SYNTHETIC_BOOKS)
    books["description"] = books["description"].astype("string")
    books["description_issue"] = books["description_issue"].astype("string")
    books["year"] = books["year"].astype("Int64")
    return books


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="path of books.parquet to write")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args(argv)
    if args.out.exists() and not args.force:
        parser.error(f"{args.out} exists (real preprocess output?). Use --force to overwrite.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    synthetic_books().to_parquet(args.out, index=False)
    manifest = args.out.parent / "manifest.json"
    manifest.write_text(json.dumps({"data_version": "synthetic-0"}, indent=2), encoding="utf-8")
    print(f"wrote {len(SYNTHETIC_BOOKS)} synthetic books to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
