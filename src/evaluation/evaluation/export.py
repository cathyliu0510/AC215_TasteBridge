"""Train B2 (ALS) on all processed data and export the backend's artifact folder.

Owner: Cathy Liu. This is the hand-off from modeling to the API (backend SPEC.md section 5):

    <out>/<model_version>/   and a copy at   <out>/current/
        books.json           [{book_id, title, author, year, shelves, cover_url}]
        item_embeddings.npy  float32 (num_books, factors), unit-length rows
        coords_2d.npy        float32 (num_books, 2), 2-D map of the embeddings in [-1, 1]
        meta.json            model_version, data_version, hyperparameters, counts

    python -m evaluation.export --processed /app/processed --out /app/artifacts

Evaluation (run.py) fits on training users only, to score held-out readers. The served
model is refitted here on ALL users with the same hyperparameters, so the app uses all data.

Row i of every file describes the same work, in catalogue order (most-liked first),
because the backend shows search hits in that order. Only works that received at least
one like have a learned vector, so works without likes are left out of the artifact.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation.als import ALS, ALSParams
from evaluation.data import load_interactions
from evaluation.run import git_commit

log = logging.getLogger("export")
MAX_SHELVES = 8  # the API's reasons use at most 3; a few more help the detail card


def map_coordinates(vectors: np.ndarray, seed: int) -> tuple[np.ndarray, str]:
    """2-D positions for the taste galaxy, scaled into [-1, 1] like the sample artifacts.

    UMAP (proposal) keeps nearby books nearby. If umap-learn is unavailable or the
    catalogue is too small for it, fall back to PCA (the top-2 principal directions).
    """
    method = "umap"
    try:
        if len(vectors) < 20:
            raise ValueError("too few books for UMAP")
        import umap  # heavy import; only needed here

        coords = umap.UMAP(n_components=2, n_neighbors=15, min_dist=0.1, metric="cosine",
                           random_state=seed).fit_transform(vectors)
    except (ImportError, ValueError) as exc:
        log.warning("UMAP unavailable (%s); using PCA for the 2-D map", exc)
        method = "pca"
        centred = vectors - vectors.mean(axis=0)
        _, _, vt = np.linalg.svd(centred, full_matrices=False)
        coords = centred @ vt[:2].T
    coords = coords - coords.mean(axis=0)
    scale = np.abs(coords).max()
    coords = coords / scale if scale > 0 else coords
    return coords.astype(np.float32), method


def build_books(books: pd.DataFrame) -> list[dict]:
    """books.parquet rows -> the backend's Book records (schemas.Book)."""
    records = []
    for row in books.itertuples(index=False):
        year = None if pd.isna(row.year) else int(row.year)
        shelves = [str(s) for s in list(row.shelves)[:MAX_SHELVES]] if row.shelves is not None else []
        records.append({
            "book_id": str(row.work_id),            # SPEC: book_id = Goodreads work_id, as a string
            "title": str(row.title) or "Untitled",
            "author": str(row.author) or "Unknown author",
            "year": year,
            "shelves": shelves,
            "cover_url": None,                      # MS2: no covers (SPEC open question 4)
        })
    return records


def check_artifacts(books: list[dict], emb: np.ndarray, coords: np.ndarray) -> None:
    """Same fail-fast rules as backend/app/artifacts.py, so a bad export never ships."""
    ids = [b["book_id"] for b in books]
    problems = []
    if not books:
        problems.append("no books")
    if len(set(ids)) != len(ids):
        problems.append("duplicate book_id")
    if any(len(i) > 64 for i in ids):
        problems.append("book_id longer than 64 chars")
    if not (len(books) == emb.shape[0] == coords.shape[0]):
        problems.append(f"row counts differ: {len(books)}, {emb.shape[0]}, {coords.shape[0]}")
    if coords.ndim != 2 or coords.shape[1] != 2:
        problems.append("coords must have 2 columns")
    if not (np.isfinite(emb).all() and np.isfinite(coords).all()):
        problems.append("NaN or infinite values")
    if (np.linalg.norm(emb, axis=1) == 0).any():
        problems.append("a book has an all-zero vector")
    if problems:
        raise ValueError("artifact check failed: " + "; ".join(problems))


def export(processed: Path, out: Path, params: ALSParams) -> Path:
    started = time.perf_counter()
    manifest = json.loads((processed / "manifest.json").read_text(encoding="utf-8"))
    data_version = manifest.get("data_version", "unknown")
    interactions = load_interactions(processed / "interactions.parquet")
    books = pd.read_parquet(processed / "books.parquet")

    model = ALS(params).fit(interactions)
    log.info("Fitted ALS on %d interactions from %d users -> %d work vectors",
             len(interactions), interactions["user_id"].nunique(), len(model.items))

    # Keep catalogue order; drop works without a learned (non-zero) vector, from both
    # tables together so row i still matches.
    row_of = {work: i for i, work in enumerate(model.items)
              if np.linalg.norm(model.item_vectors[i]) > 0}
    books = books[books["work_id"].astype(str).isin(row_of)].reset_index(drop=True)
    emb = model.item_vectors[[row_of[w] for w in books["work_id"].astype(str)]]
    coords, method = map_coordinates(emb, params.seed)
    records = build_books(books)
    check_artifacts(records, emb, coords)

    model_version = f"b2-als-{data_version}"
    target = out / model_version
    tmp = out / f".{model_version}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    (tmp / "books.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    np.save(tmp / "item_embeddings.npy", emb.astype(np.float32))
    np.save(tmp / "coords_2d.npy", coords)
    meta = {
        "model_version": model_version,
        "model": "B2 implicit ALS (Hu, Koren & Volinsky 2008), numpy implementation",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "data_version": data_version,
        "hyperparameters": params.as_dict(),
        "scoring": "taste = unit mean of seed vectors; fit = cosine; served by backend/app/recommender.py",
        "map_method": method,
        "counts": {"books": len(records), "interactions": int(len(interactions)),
                   "users": int(interactions["user_id"].nunique())},
        "code_version": git_commit(),
        "seconds": round(time.perf_counter() - started, 1),
    }
    (tmp / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    current = out / "current"                     # what the backend loads
    shutil.rmtree(current, ignore_errors=True)
    shutil.copytree(target, current)
    log.info("Exported %s: %d books, %s map -> %s (and %s)", model_version, len(records), method, target, current)
    return target


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--processed", type=Path, default=Path("/app/processed"))
    p.add_argument("--out", type=Path, default=Path("/app/artifacts"))
    p.add_argument("--als-factors", type=int, default=ALSParams.factors)
    p.add_argument("--als-reg", type=float, default=ALSParams.regularization)
    p.add_argument("--als-alpha", type=float, default=ALSParams.alpha)
    p.add_argument("--als-iterations", type=int, default=ALSParams.iterations)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)
    params = ALSParams(factors=args.als_factors, regularization=args.als_reg, alpha=args.als_alpha,
                       iterations=args.als_iterations, seed=args.seed)
    try:
        export(args.processed, args.out, params)
    except (FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
