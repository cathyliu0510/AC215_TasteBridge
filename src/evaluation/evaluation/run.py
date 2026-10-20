"""Run the pair-simulation evaluation and write a results folder.

    python -m evaluation.run --interactions data/interactions.parquet --books data/books.parquet
    python -m evaluation.run --synthetic        # no dataset needed

Writes <out>/<run_id>/:
    config.json                 arguments, data versions, split sizes, code version
    summary.csv / summary.md    metrics per model x aggregation x favorites x pair kind
    per_pair.csv                one row per evaluated pair list
    sample_recommendations.json a few readable input -> output examples
    run.log                     the full log of this run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation import __version__, synthetic
from evaluation.aggregate import AGGREGATIONS, recommend_pair
from evaluation.data import data_version, likes, load_books, load_interactions
from evaluation.metrics import coverage, long_tail, pair_metrics
from evaluation.als import ALS, ALSParams
from evaluation.models import MODELS, ItemKNN
from evaluation.pairs import sample_pairs
from evaluation.split import make_eval_readers, split_users

log = logging.getLogger("evaluation")
METRIC_COLUMNS = ("min_recall", "mean_ndcg", "recall_a", "recall_b")
N_EXAMPLES = 3


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    csv = lambda value: [v.strip() for v in value.split(",") if v.strip()]  # noqa: E731
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--interactions", help="interactions table (csv/parquet/jsonl)")
    p.add_argument("--books", help="books table with a genres column")
    p.add_argument("--synthetic", action="store_true", help="generate synthetic data instead")
    p.add_argument("--out", default="results")
    p.add_argument("--run-id", default=None)
    p.add_argument("--split", choices=("tune", "test"), default="test")
    p.add_argument("--models", type=csv, default=["popularity", "item_knn", "als"])
    p.add_argument("--aggregations", type=csv, default=list(AGGREGATIONS))
    p.add_argument("--favorite-counts", type=csv, default=["5"], help="e.g. 1,2,3,4,5 for robustness")
    p.add_argument("--n-pairs", type=int, default=300)
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--knn-neighbors", type=int, default=100)
    p.add_argument("--seed", type=int, default=42)
    # B2 ALS hyperparameters (defaults in evaluation/als.py ALSParams)
    p.add_argument("--als-factors", type=int, default=ALSParams.factors)
    p.add_argument("--als-reg", type=float, default=ALSParams.regularization)
    p.add_argument("--als-alpha", type=float, default=ALSParams.alpha)
    p.add_argument("--als-iterations", type=int, default=ALSParams.iterations)
    args = p.parse_args(argv)
    if not args.synthetic and not (args.interactions and args.books):
        p.error("give --interactions and --books, or --synthetic")
    for name in args.models:
        if name not in MODELS:
            p.error(f"unknown model {name!r}; choose from {sorted(MODELS)}")
    for name in args.aggregations:
        if name not in AGGREGATIONS:
            p.error(f"unknown aggregation {name!r}; choose from {list(AGGREGATIONS)}")
    args.favorite_counts = sorted({int(n) for n in args.favorite_counts}, reverse=True)
    if not all(1 <= n <= 5 for n in args.favorite_counts):
        p.error("--favorite-counts must be between 1 and 5")
    return args


def als_params(args: argparse.Namespace) -> ALSParams:
    return ALSParams(factors=args.als_factors, regularization=args.als_reg, alpha=args.als_alpha,
                     iterations=args.als_iterations, seed=args.seed)


def git_commit() -> str | None:
    if os.environ.get("GIT_COMMIT"):
        return os.environ["GIT_COMMIT"]
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
            cwd=Path(__file__).resolve().parent,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def setup_logging(run_dir: Path) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    log.handlers.clear()
    log.setLevel(logging.INFO)
    log.propagate = False
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(run_dir / "run.log")):
        handler.setFormatter(fmt)
        log.addHandler(handler)


def summarise(per_pair: pd.DataFrame, lists: dict, catalogue: set[str], tail: frozenset[str]) -> pd.DataFrame:
    rows = []
    keys = ["model", "aggregation", "n_favorites"]
    for group_key, group in per_pair.groupby(keys, sort=False):
        for kind in ("all", "similar", "different"):
            part = group if kind == "all" else group[group["pair_kind"] == kind]
            if part.empty:
                continue
            row = dict(zip(keys, group_key), pair_kind=kind, n_pairs=len(part))
            for metric in METRIC_COLUMNS:
                values = part[metric].to_numpy(dtype=float)
                row[metric] = values.mean()
                row[f"{metric}_ci95"] = 1.96 * values.std(ddof=1) / np.sqrt(len(values)) if len(values) > 1 else 0.0
            eligible = part["both_hit"].dropna()
            row["both_hit_eligible_share"] = len(eligible) / len(part)
            row["both_hit"] = float(eligible.astype(bool).mean()) if len(eligible) else np.nan
            row.update(coverage([lists[(*group_key, i)] for i in part["pair_index"]], catalogue, tail))
            rows.append(row)
    return pd.DataFrame(rows)


def to_markdown(summary: pd.DataFrame) -> str:
    cols = ["model", "aggregation", "n_favorites", "pair_kind", "n_pairs",
            "min_recall", "mean_ndcg", "both_hit", "long_tail_coverage", "catalogue_coverage"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in summary.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if c in ("min_recall", "mean_ndcg"):
                cells.append(f"{v:.4f} ± {r[c + '_ci95']:.4f}")
            elif isinstance(v, float):
                cells.append("n/a" if np.isnan(v) else f"{v:.4f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> Path:
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.out) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(run_dir)
    started = time.perf_counter()
    log.info("TasteBridge evaluation %s, run %s", __version__, run_id)

    if args.synthetic:
        interactions_path, books_path = synthetic.write(run_dir / "input", seed=args.seed)
        log.info("Generated synthetic input in %s", run_dir / "input")
    else:
        interactions_path, books_path = Path(args.interactions), Path(args.books)
    interactions = load_interactions(interactions_path)
    books = load_books(books_path)
    log.info("Loaded %d interactions from %d users; %d books",
             len(interactions), interactions["user_id"].nunique(), len(books))

    split = split_users(interactions["user_id"], seed=args.seed)
    train = interactions[interactions["user_id"].isin(split.train)]
    log.info("User split train/tune/test = %d/%d/%d", len(split.train), len(split.tune), len(split.test))
    if set(train["user_id"]) & split.users(args.split):
        raise RuntimeError("evaluation users leaked into training data")

    popularity = likes(train).groupby("work_id").size().to_dict()
    catalogue = set(popularity)
    tail = long_tail(popularity)
    readers = make_eval_readers(interactions, split.users(args.split), catalogue, seed=args.seed)
    log.info("%d %s readers have >=15 likes in the %d-work catalogue", len(readers), args.split, len(catalogue))
    book_genres = dict(zip(books["work_id"], books["genres"]))
    pairs = sample_pairs(readers, book_genres, args.n_pairs, seed=args.seed)
    kinds = pd.Series([p.kind for p in pairs]).value_counts().to_dict()
    log.info("Sampled %d pairs %s", len(pairs), kinds)

    models = {}
    for name in args.models:
        tic = time.perf_counter()
        if name == "item_knn":
            model = ItemKNN(args.knn_neighbors)
        elif name == "als":
            model = ALS(als_params(args))
        else:
            model = MODELS[name]()
        models[name] = model.fit(train)
        log.info("Fitted %s on %d training interactions in %.2fs", name, len(train), time.perf_counter() - tic)

    rows, lists = [], {}
    for name, model in models.items():
        for aggregation in args.aggregations:
            for n_fav in args.favorite_counts:
                for index, pair in enumerate(pairs):
                    a, b = pair.a.with_favorites(n_fav), pair.b.with_favorites(n_fav)
                    ranked = recommend_pair(model, a.favorites, b.favorites, args.k, aggregation)
                    lists[(name, aggregation, n_fav, index)] = ranked
                    rows.append({"model": name, "aggregation": aggregation, "n_favorites": n_fav,
                                 "pair_index": index, "pair_kind": pair.kind,
                                 "genre_similarity": round(pair.genre_similarity, 4),
                                 "reader_a": a.user_id, "reader_b": b.user_id,
                                 **pair_metrics(ranked, a.hidden, b.hidden, args.k)})
    per_pair = pd.DataFrame(rows)
    summary = summarise(per_pair, lists, catalogue, tail)

    per_pair.to_csv(run_dir / "per_pair.csv", index=False)
    summary.to_csv(run_dir / "summary.csv", index=False, float_format="%.6f")
    (run_dir / "summary.md").write_text(to_markdown(summary))

    titles = dict(zip(books["work_id"], books.get("title", books["work_id"])))
    examples = []
    for index, pair in enumerate(pairs[:N_EXAMPLES]):
        name, aggregation, n_fav = args.models[-1], args.aggregations[0], args.favorite_counts[0]
        ranked = lists[(name, aggregation, n_fav, index)]
        examples.append({
            "model": name, "aggregation": aggregation, "pair_kind": pair.kind,
            "input": {"reader_a_favorites": [titles.get(w, w) for w in pair.a.favorites[:n_fav]],
                      "reader_b_favorites": [titles.get(w, w) for w in pair.b.favorites[:n_fav]]},
            "output": [{"rank": r + 1, "work_id": w, "title": titles.get(w, w),
                        "hidden_like_of": [x for x, h in (("a", pair.a.hidden), ("b", pair.b.hidden)) if w in h]}
                       for r, w in enumerate(ranked)],
        })
    (run_dir / "sample_recommendations.json").write_text(json.dumps(examples, indent=2))

    config = {
        "run_id": run_id, "package_version": __version__, "git_commit": git_commit(),
        "python": platform.python_version(), "arguments": {k: v for k, v in vars(args).items()},
        "data": {"interactions": data_version(interactions_path), "books": data_version(books_path)},
        "counts": {"interactions": len(interactions), "train_interactions": len(train),
                   "users": {"train": len(split.train), "tune": len(split.tune), "test": len(split.test)},
                   "catalogue_works": len(catalogue), "long_tail_works": len(tail),
                   "eligible_readers": len(readers), "pairs": kinds},
        "seconds": round(time.perf_counter() - started, 2),
    }
    (run_dir / "config.json").write_text(json.dumps(config, indent=2, default=str))

    headline = summary[(summary["pair_kind"] == "all") & (summary["n_favorites"] == args.favorite_counts[0])]
    for _, r in headline.iterrows():
        log.info("%-10s %-12s Min-Recall@%d %.4f  NDCG@%d %.4f  long-tail cov %.4f",
                 r["model"], r["aggregation"], args.k, r["min_recall"], args.k, r["mean_ndcg"], r["long_tail_coverage"])
    log.info("Wrote results to %s in %.1fs", run_dir, config["seconds"])
    return run_dir


def main(argv: list[str] | None = None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()
