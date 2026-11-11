"""Write, check and publish M1's copy of the backend artifact contract (backend SPEC.md section 5).

Every train image in the shared pipeline (M1 two-tower, B2 ALS) hands over the same four files,
so check, evaluate, gate and export work unchanged for either model, and the app's backend
could load either one without a code change:

    books.json           [{book_id, title, author, year, shelves, cover_url}]   (catalogue order)
    item_embeddings.npy  float32 (num_books, d), unit rows, row i <-> books.json[i]
    coords_2d.npy        float32 (num_books, 2) in [-1, 1], the "taste galaxy" map
    meta.json            model_version, data_version, wandb_run_id, created_at, ...

M1 keeps its own files next to them: two_tower.pt, items.json (the network's internal row
order, used by TwoTower.load) and params.json. The backend's mean-of-favourites cosine over
item_embeddings.npy is a single-vector fallback; M1's multi-interest score needs two_tower.pt.

The formats come from Cathy's B2 exporter (evaluation.export: build_books, map_coordinates,
check_artifacts), reused rather than copied, so the two models cannot drift apart.

    python -m twotower.export write   --model-dir RUN/model --data-dir DATA [--run-id ID] [--wandb-run-id ID]
    python -m twotower.export check   DIR
    python -m twotower.export publish --model-dir RUN/model --out MODELS_ROOT
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from twotower._evaluation import ensure_evaluation
from twotower.data import DataPaths
from twotower.recommender import TwoTower

ensure_evaluation()

from evaluation.export import build_books, check_artifacts, map_coordinates  # noqa: E402

log = logging.getLogger("twotower.export")

CONTRACT_FILES = ("books.json", "item_embeddings.npy", "coords_2d.npy", "meta.json")
M1_FILES = ("two_tower.pt", "items.json", "params.json")
REQUIRED_META = ("model_version", "data_version", "wandb_run_id")  # MS3-collaboration.md section 3
MIN_UMAP_BOOKS = 20  # evaluation.export.map_coordinates uses PCA below this size


def model_version_for(data_version: str, run_id: str) -> str:
    return f"m1-tt-{data_version}-{run_id}"


def write_contract(
    model: TwoTower,
    books_path: str | Path,
    out: str | Path,
    *,
    data_version: str,
    run_id: str,
    wandb_run_id: str | None,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the four contract files into `out` (normally RUN/model, next to M1's own files).

    Rows follow the catalogue order of books.parquet, like the B2 export, restricted to the
    works the model has a vector for (works liked by at least one TRAIN reader).
    The 2-D map is UMAP, as in the proposal. The shared map_coordinates falls back to PCA when
    umap-learn is missing; here that is an error, so a broken environment can't silently ship a
    different map. (Catalogues under 20 books, i.e. tiny test fixtures, still use PCA.)
    Returns the meta.json content.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    books = pd.read_parquet(books_path)
    vectors = model.item_vectors()
    row_of = {w: i for i, w in enumerate(model.items)}
    books = books[books["work_id"].astype(str).isin(row_of)].reset_index(drop=True)
    emb = vectors[[row_of[w] for w in books["work_id"].astype(str)]].astype(np.float32)
    coords, method = map_coordinates(emb, model.p.seed)
    if method != "umap" and len(emb) >= MIN_UMAP_BOOKS:
        raise RuntimeError("UMAP is required for the 2-D map but unavailable: install umap-learn (pyproject.toml)")
    records = build_books(_with_optional_columns(books))
    check_artifacts(records, emb, coords)

    meta: dict[str, Any] = {
        "model_version": model_version_for(data_version, run_id),
        "model": "M1 two-tower: MiniLM item tower + set-Transformer reader tower, multi-interest readout",
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "data_version": data_version,
        "run_id": run_id,
        "wandb_run_id": wandb_run_id,
        "hyperparameters": model.p.as_dict(),
        "scoring": (
            "M1 score = tau*logsumexp_j(cos(u_j, z_i)/tau) via two_tower.pt; "
            "item_embeddings.npy alone supports the backend's mean-of-favourites cosine (fallback)"
        ),
        "map_method": method,
        "counts": {"books": len(records), "model_items": len(model.items)},
        "code_version": os.environ.get("GIT_COMMIT"),
        **(extra_meta or {}),
    }
    (out / "books.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    np.save(out / "item_embeddings.npy", emb)
    np.save(out / "coords_2d.npy", coords)
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")  # last = complete
    log.info("contract written: %s, %d books, %s map -> %s", meta["model_version"], len(records), method, out)
    return meta


def _with_optional_columns(books: pd.DataFrame) -> pd.DataFrame:
    """The real books.parquet has year and shelves; the evaluator's synthetic catalogue only has
    `genres` ("a|b"). Fill the two optional Book fields so both export the same record shape."""
    books = books.copy()
    if "year" not in books.columns:
        books["year"] = pd.NA
    if "shelves" not in books.columns:
        genres = books["genres"] if "genres" in books.columns else pd.Series([None] * len(books))
        books["shelves"] = [
            [g for g in v.split("|") if g] if isinstance(v, str) else list(v) if v is not None else [] for v in genres
        ]
    return books


def check_contract(path: str | Path) -> dict[str, Any]:
    """Validate a contract folder (M1's or ALS's) the way the backend would, plus the MS3 meta keys.

    Raises ValueError listing every problem; returns meta.json on success.
    """
    path = Path(path)
    missing = [f for f in CONTRACT_FILES if not (path / f).is_file()]
    if missing:
        raise ValueError(f"contract check failed for {path}: missing {', '.join(missing)}")
    books = json.loads((path / "books.json").read_text(encoding="utf-8"))
    emb = np.load(path / "item_embeddings.npy")
    coords = np.load(path / "coords_2d.npy")
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))

    problems: list[str] = []
    try:
        check_artifacts(books, emb, coords)
    except ValueError as exc:
        problems.append(str(exc))
    if emb.dtype != np.float32 or coords.dtype != np.float32:
        problems.append(f"arrays must be float32 (got {emb.dtype}, {coords.dtype})")
    if emb.ndim == 2 and len(emb) and np.isfinite(emb).all():
        norms = np.linalg.norm(emb.astype(np.float64), axis=1)
        if np.abs(norms - 1).max() > 1e-3:
            problems.append("item_embeddings.npy rows are not L2-normalised")
    for key in REQUIRED_META:
        if key not in meta:
            problems.append(f"meta.json lacks {key!r}")
    for key in ("model_version", "data_version"):
        if key in meta and not (isinstance(meta[key], str) and meta[key].strip()):
            problems.append(f"meta.json {key!r} must be a non-empty string")
    if "wandb_run_id" in meta and meta["wandb_run_id"] is not None and not isinstance(meta["wandb_run_id"], str):
        problems.append("meta.json 'wandb_run_id' must be a string or null")
    if problems:
        raise ValueError(f"contract check failed for {path}: " + "; ".join(problems))
    return dict(meta)


def publish(model_dir: str | Path, out_root: str | Path) -> Path:
    """Copy a checked model folder to <out_root>/<model_version>/ (the pipeline's export step).

    A published version is never overwritten. Files are copied one by one, meta.json last, with
    no directory rename, because renaming folders is not reliable on the /gcs FUSE mount.
    """
    model_dir = Path(model_dir)
    meta = check_contract(model_dir)
    target = Path(out_root) / meta["model_version"]
    if (target / "meta.json").exists():
        raise FileExistsError(f"{target} is already published; model versions are immutable")
    target.mkdir(parents=True, exist_ok=True)
    names = [f for f in (*M1_FILES, *CONTRACT_FILES) if f != "meta.json" and (model_dir / f).is_file()]
    for name in [*names, "meta.json"]:
        shutil.copyfile(model_dir / name, target / name)
    log.info("published %s -> %s", meta["model_version"], target)
    return target


def _write_from_saved(a: argparse.Namespace) -> dict[str, Any]:
    data = DataPaths(Path(a.data_dir))
    model_dir = Path(a.model_dir)
    model = TwoTower.load(model_dir, device="cpu")
    saved = json.loads((model_dir / "params.json").read_text())
    data_version = a.data_version or data.version().get("data_version") or saved.get("data_version")
    run_id = a.run_id or saved.get("run_id")
    if not data_version or not run_id:
        raise SystemExit("need --data-version and --run-id (not found in processed/manifest.json or params.json)")
    return write_contract(
        model, data.books, model_dir, data_version=data_version, run_id=run_id, wandb_run_id=a.wandb_run_id
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="add the 4 contract files to a saved M1 model folder")
    w.add_argument("--model-dir", required=True)
    w.add_argument("--data-dir", required=True, help="folder with processed/ (books.parquet, manifest.json)")
    w.add_argument("--run-id", default=None, help="default: run_id in params.json")
    w.add_argument("--data-version", default=None, help="default: processed/manifest.json")
    w.add_argument("--wandb-run-id", default=None)
    c = sub.add_parser("check", help="validate a contract folder (exit 1 on failure)")
    c.add_argument("dir")
    p = sub.add_parser("publish", help="check, then copy to <out>/<model_version>/")
    p.add_argument("--model-dir", required=True)
    p.add_argument("--out", required=True, help="models root, e.g. /gcs/tastebridge-twotower/models")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if a.cmd == "write":
        meta = _write_from_saved(a)
        print(meta["model_version"])
    elif a.cmd == "check":
        try:
            meta = check_contract(a.dir)
        except ValueError as exc:
            log.error("%s", exc)
            return 1
        n_books = len(np.load(Path(a.dir) / "item_embeddings.npy"))
        print(f"OK {meta['model_version']}: {n_books} books")
    else:
        print(publish(a.model_dir, a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
