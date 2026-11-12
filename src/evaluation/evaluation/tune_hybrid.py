"""Tune the M1 hybrid on the tune split, then evaluate it once on the test split.

    python -m evaluation.tune_hybrid --interactions data/interactions.parquet --books data/books.parquet
    python -m evaluation.tune_hybrid --synthetic          # no dataset needed

Protocol (same as B2's tuning in docs/ms2/models/README.md):
  1. Fit item-kNN (one per neighbour count) and ALS once, on training users only.
  2. Score every grid setting on the TUNE pairs (average aggregation, five favorites):
     weight w x neighbour count x ALS scoring rule. w = 1 gives exactly B1's lists,
     so with B1's neighbour count (100) in the grid the chosen setting is never
     below B1 on the tune split.
  3. Pick the best Min-Recall@10 and write it to best.json.
  4. Run the normal evaluation (evaluation.run) on the TEST split with that setting,
     next to B0, B1, B2 and ALS fold-in. The test split is used exactly once.

Writes <out>/<run_id>-tune/ (tuning.csv, tuning.md, best.json, run.log) and
<out>/<run_id>-test/ (the standard evaluation results folder).
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation import synthetic
from evaluation import run as run_module
from evaluation.aggregate import recommend_pair
from evaluation.als import ALS, ALSParams
from evaluation.data import data_version, likes, load_books, load_interactions
from evaluation.hybrid import ALS_SCORINGS, ALSFoldIn, HybridParams, rescale
from evaluation.metrics import pair_metrics
from evaluation.models import ItemKNN, Popularity
from evaluation.pairs import sample_pairs
from evaluation.split import make_eval_readers, split_users

log = logging.getLogger("evaluation")
DEFAULT_WEIGHTS = [round(0.1 * i, 1) for i in range(11)]
DEFAULT_NEIGHBORS = [50, 100, 200]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    csv = lambda value: [v.strip() for v in value.split(",") if v.strip()]  # noqa: E731
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--interactions")
    p.add_argument("--books")
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--out", default="results")
    p.add_argument("--run-id", default=None)
    p.add_argument("--weights", type=csv, default=[str(w) for w in DEFAULT_WEIGHTS])
    p.add_argument("--neighbors", type=csv, default=[str(n) for n in DEFAULT_NEIGHBORS])
    p.add_argument("--als-scorings", type=csv, default=list(ALS_SCORINGS))
    p.add_argument("--n-pairs", type=int, default=300)
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--knn-neighbors", type=int, default=100, help="B1 in the final test run (MS2: 100)")
    p.add_argument("--favorite-counts", default="5", help="for the final test run, e.g. 1,2,3,4,5")
    p.add_argument("--als-factors", type=int, default=ALSParams.factors)
    p.add_argument("--als-reg", type=float, default=ALSParams.regularization)
    p.add_argument("--als-alpha", type=float, default=ALSParams.alpha)
    p.add_argument("--als-iterations", type=int, default=ALSParams.iterations)
    p.add_argument("--skip-test", action="store_true", help="tune only; do not touch the test split")
    args = p.parse_args(argv)
    if not args.synthetic and not (args.interactions and args.books):
        p.error("give --interactions and --books, or --synthetic")
    try:
        args.weights = sorted({float(w) for w in args.weights})
        args.neighbors = sorted({int(n) for n in args.neighbors})
    except ValueError as exc:
        p.error(str(exc))
    if not args.weights or not all(0.0 <= w <= 1.0 for w in args.weights):
        p.error("--weights must be numbers between 0 and 1")
    if not args.neighbors or min(args.neighbors) < 1:
        p.error("--neighbors must be positive integers")
    for scoring in args.als_scorings:
        if scoring not in ALS_SCORINGS:
            p.error(f"unknown ALS scoring {scoring!r}; choose from {list(ALS_SCORINGS)}")
    return args


class _Blend:
    """Hybrid scores from cached per-reader components (same arithmetic as Hybrid.score)."""

    def __init__(self, items, knn_cache, als_cache, weight):
        self.items, self._knn, self._als, self.weight = items, knn_cache, als_cache, weight

    def score(self, favorites):
        key = tuple(favorites)
        if self.weight == 1.0:
            return self._knn(key)
        if self.weight == 0.0:
            return self._als(key)
        return self.weight * self._knn(key) + (1.0 - self.weight) * self._als(key)


def _cached(fn):
    store: dict = {}

    def get(key):
        if key not in store:
            store[key] = fn(key)
        return store[key]

    return get


def _evaluate(model, pairs, k: int) -> dict:
    rows = []
    for pair in pairs:
        ranked = recommend_pair(model, pair.a.favorites, pair.b.favorites, k, "average")
        rows.append({"kind": pair.kind, **pair_metrics(ranked, pair.a.hidden, pair.b.hidden, k)})
    frame = pd.DataFrame(rows)
    values = frame["min_recall"].to_numpy(dtype=float)
    return {
        "min_recall": values.mean(),
        "min_recall_ci95": 1.96 * values.std(ddof=1) / np.sqrt(len(values)) if len(values) > 1 else 0.0,
        "mean_ndcg": frame["mean_ndcg"].mean(),
        "min_recall_similar": frame.loc[frame["kind"] == "similar", "min_recall"].mean(),
        "min_recall_different": frame.loc[frame["kind"] == "different", "min_recall"].mean(),
    }


def _markdown(grid: pd.DataFrame, references: dict, best: dict) -> str:
    columns = [(n, s) for n in sorted(grid["knn_neighbors"].unique()) for s in ALS_SCORINGS
               if s in set(grid["als_scoring"])]
    header = "| item-kNN weight w | " + " | ".join(f"{n} nbrs, {s.replace('_', '-')}" for n, s in columns) + " |"
    lines = [
        "# M1 hybrid tuning (tune split)", "",
        "Min-Recall@10, average aggregation, five favorites. w = 1 is exactly item-kNN (B1); "
        "w = 0 is ALS alone, rescaled per reader. **Bold** = chosen.", "",
        header, "|" + "---|" * (len(columns) + 1),
    ]
    for w in sorted(grid["weight"].unique()):
        cells = []
        for n, s in columns:
            hit = grid[(grid["weight"] == w) & (grid["knn_neighbors"] == n) & (grid["als_scoring"] == s)]
            value = f"{hit['min_recall'].iloc[0]:.4f}"
            chosen = (w == best["weight"] and n == best["knn_neighbors"] and s == best["als_scoring"])
            cells.append(f"**{value}**" if chosen else value)
        lines.append(f"| {w:.1f} | " + " | ".join(cells) + " |")
    lines += ["", "Reference models on the same tune pairs:", ""]
    lines += [f"- {name}: {value:.4f}" for name, value in references.items()]
    return "\n".join(lines) + "\n"


def tune(args: argparse.Namespace) -> Path:
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tune_dir = Path(args.out) / f"{run_id}-tune"
    tune_dir.mkdir(parents=True, exist_ok=True)
    run_module.setup_logging(tune_dir)
    started = time.perf_counter()
    log.info("M1 hybrid tuning, run %s", run_id)

    if args.synthetic:
        interactions_path, books_path = synthetic.write(tune_dir / "input", seed=args.seed)
    else:
        interactions_path, books_path = Path(args.interactions), Path(args.books)
    interactions = load_interactions(interactions_path)
    books = load_books(books_path)

    # Identical setup to evaluation.run, so the tune pairs match `run --split tune`.
    split = split_users(interactions["user_id"], seed=args.seed)
    train = interactions[interactions["user_id"].isin(split.train)]
    if set(train["user_id"]) & split.tune:
        raise RuntimeError("tune users leaked into training data")
    catalogue = set(likes(train)["work_id"])
    readers = make_eval_readers(interactions, split.tune, catalogue, seed=args.seed)
    pairs = sample_pairs(readers, dict(zip(books["work_id"], books["genres"])), args.n_pairs, seed=args.seed)
    log.info("Tune split: %d readers, %d pairs; %d training interactions", len(readers), len(pairs), len(train))

    als_params = ALSParams(factors=args.als_factors, regularization=args.als_reg, alpha=args.als_alpha,
                           iterations=args.als_iterations, seed=args.seed)
    tic = time.perf_counter()
    als = ALS(als_params).fit(train)
    fold_in = ALSFoldIn.from_als(als)
    log.info("Fitted ALS %s in %.1fs", als_params.as_dict(), time.perf_counter() - tic)
    knns = {n: ItemKNN(n).fit(train) for n in args.neighbors}
    items = als.items
    for n, knn in knns.items():
        if tuple(knn.items) != tuple(items):
            raise RuntimeError("item-kNN and ALS catalogues differ")

    als_scores = {"fold_in": fold_in.score, "cosine": als.score}
    als_cache = {s: _cached(lambda key, s=s: rescale(als_scores[s](key), items, key)) for s in args.als_scorings}
    knn_cache = {n: _cached(lambda key, n=n: knns[n].score(key)) for n in args.neighbors}  # B1's own scale

    rows = []
    for n in args.neighbors:
        for scoring in args.als_scorings:
            for w in args.weights:
                metrics = _evaluate(_Blend(items, knn_cache[n], als_cache[scoring], w), pairs, args.k)
                rows.append({"knn_neighbors": n, "als_scoring": scoring, "weight": w, **metrics})
                log.info("nbrs %-4d %-8s w %.2f  Min-Recall@%d %.4f", n, scoring, w, args.k, metrics["min_recall"])
    grid = pd.DataFrame(rows)

    # Best Min-Recall; ties go to the larger kNN weight (closer to the proven B1), then fewer neighbours.
    order = grid.sort_values(["min_recall", "weight", "knn_neighbors"], ascending=[False, False, True],
                             kind="stable")
    top = order.iloc[0]
    best = HybridParams(weight=float(top["weight"]), knn_neighbors=int(top["knn_neighbors"]),
                        als_scoring=str(top["als_scoring"]))

    references = {
        "B0 popularity": _evaluate(Popularity().fit(train), pairs, args.k)["min_recall"],
        f"B1 item-kNN ({args.knn_neighbors} neighbours)": _evaluate(
            knns.get(args.knn_neighbors) or ItemKNN(args.knn_neighbors).fit(train), pairs, args.k)["min_recall"],
        "B2 ALS (cosine, as served)": _evaluate(als, pairs, args.k)["min_recall"],
        "ALS fold-in": _evaluate(fold_in, pairs, args.k)["min_recall"],
    }
    for name, value in references.items():
        log.info("Reference %-32s Min-Recall@%d %.4f", name, args.k, value)

    grid.to_csv(tune_dir / "tuning.csv", index=False, float_format="%.6f")
    (tune_dir / "tuning.md").write_text(_markdown(grid, references, best.as_dict()))
    best_record = {
        "run_id": run_id,
        "hybrid": best.as_dict(),
        "tune": {"split": "tune", "pairs": len(pairs),
                 **{key: float(top[key]) for key in ("min_recall", "min_recall_ci95", "mean_ndcg",
                                                     "min_recall_similar", "min_recall_different")},
                 "references": {k: float(v) for k, v in references.items()}},
        "als": als_params.as_dict(),
        "grid": {"weights": args.weights, "neighbors": args.neighbors, "als_scorings": args.als_scorings},
        "data": {"interactions": data_version(interactions_path), "books": data_version(books_path)},
        "git_commit": run_module.git_commit(),
        "seconds": round(time.perf_counter() - started, 2),
    }
    best_path = tune_dir / "best.json"
    best_path.write_text(json.dumps(best_record, indent=2, default=str))
    log.info("Chosen on the tune split: %s, Min-Recall@%d %.4f (B1 %.4f)", best.as_dict(), args.k,
             top["min_recall"], references[f"B1 item-kNN ({args.knn_neighbors} neighbours)"])
    log.info("Wrote %s", tune_dir)

    if args.skip_test:
        return tune_dir
    test_argv = [
        "--interactions", str(interactions_path), "--books", str(books_path),
        "--out", str(args.out), "--run-id", f"{run_id}-test", "--split", "test",
        "--models", "popularity,item_knn,als,als_foldin,hybrid",
        "--hybrid-params", str(best_path), "--knn-neighbors", str(args.knn_neighbors),
        "--favorite-counts", args.favorite_counts, "--n-pairs", str(args.n_pairs), "--k", str(args.k),
        "--seed", str(args.seed), "--als-factors", str(args.als_factors), "--als-reg", str(args.als_reg),
        "--als-alpha", str(args.als_alpha), "--als-iterations", str(args.als_iterations),
    ]
    return run_module.run(run_module.parse_args(test_argv))


def main(argv: list[str] | None = None) -> None:
    tune(parse_args(argv))


if __name__ == "__main__":
    main()
