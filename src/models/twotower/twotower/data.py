"""Where the inputs live and how they are read.

One rule keeps local and cloud runs identical: every path comes from `--data-dir`.
`--data-dir` holds two folders, the outputs of the MS2 pipeline:

    <data-dir>/processed/   books.parquet, interactions.parquet, manifest.json   (preprocess stage)
    <data-dir>/embeddings/  desc_embeddings.npy, desc_rows.parquet, meta.json     (embed stage)

Locally <data-dir> is `../../../data` (or `/data` inside the container). On Vertex AI it is
`/gcs/<bucket>/data/<data_version>`, the Cloud Storage FUSE mount of the same two folders.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Fixed ids for the real catalogue's `genre` column, in the order the local experiments used.
REAL_GENRES = {"fantasy": 0, "mystery": 1, "both": 2}


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @property
    def processed(self) -> Path:
        return self.root / "processed"

    @property
    def embeddings(self) -> Path:
        return self.root / "embeddings"

    @property
    def interactions(self) -> Path:
        return self.processed / "interactions.parquet"

    @property
    def books(self) -> Path:
        return self.processed / "books.parquet"

    @property
    def desc_embeddings(self) -> Path:
        return self.embeddings / "desc_embeddings.npy"

    @property
    def desc_rows(self) -> Path:
        return self.embeddings / "desc_rows.parquet"

    def content_paths(self) -> dict[str, Path]:
        """The keyword arguments of `load_content` (and of `TwoTower(content_paths=...)`)."""
        return {"books_path": self.books, "emb_path": self.desc_embeddings, "rows_path": self.desc_rows}

    def check(self) -> None:
        missing = [
            str(p) for p in (self.interactions, self.books, self.desc_embeddings, self.desc_rows) if not p.exists()
        ]
        if missing:
            raise FileNotFoundError(
                "missing input files (run `dvc pull` or the MS2 pipeline first): " + ", ".join(missing)
            )

    def version(self) -> dict[str, Any]:
        """Data lineage for the run config: the processed data_version and the embedding model."""
        out: dict[str, Any] = {}
        manifest = self.processed / "manifest.json"
        if manifest.exists():
            m = json.loads(manifest.read_text())
            out["data_version"] = m.get("data_version")
            out["processed_created_at"] = m.get("created_at")
        meta = self.embeddings / "meta.json"
        if meta.exists():
            e = json.loads(meta.read_text())
            out["embedding_model"] = e.get("embedding_model")
            out["embedding_model_revision"] = e.get("model_revision")
            out["embedding_input_data_version"] = e.get("input_data_version")
        return out


def load_content(
    books_path: str | Path, emb_path: str | Path, rows_path: str | Path
) -> tuple[dict[str, int], np.ndarray, dict[str, int], int]:
    """Returns work_id -> row of the MiniLM matrix, the matrix, work_id -> genre id, and #genres.

    The real catalogue has a `genre` column (fantasy / mystery / both). Other catalogues (the
    synthetic one in tests) only have `genres`; their first genre is used.
    """
    rows = pd.read_parquet(rows_path)
    emb = np.load(emb_path).astype(np.float32)
    row_of = dict(zip(rows["work_id"].astype(str), rows["row"].astype(int), strict=True))
    books = pd.read_parquet(books_path)
    if "genre" in books.columns:
        vocab = dict(REAL_GENRES)
        labels = books["genre"].astype(str)
    else:
        labels = books["genres"].map(_first_genre)
        vocab = {g: i for i, g in enumerate(sorted(set(labels)))}
    for g in sorted(set(labels) - set(vocab)):
        vocab[g] = len(vocab)
    genre_of = {str(w): vocab[g] for w, g in zip(books["work_id"], labels, strict=True)}
    return row_of, emb, genre_of, max(len(vocab), 1)


def _first_genre(value: object) -> str:
    if isinstance(value, str):
        parts = value.split("|")
    elif value is None or (isinstance(value, float) and np.isnan(value)):
        parts = []
    else:
        parts = [str(v) for v in value]  # type: ignore[attr-defined]
    return parts[0].strip() if parts and parts[0].strip() else "unknown"
