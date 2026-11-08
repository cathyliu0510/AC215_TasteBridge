"""Score a trained M1 with the team's unchanged evaluator, next to the baselines.

    python -m twotower.evaluate --data-dir DATA --model-dir RUN/model --out RUN

Writes <out>/test-eval/ (the evaluator's config.json, summary.csv, summary.md, per_pair.csv),
<out>/headline.csv and <out>/metrics.json. metrics.json is what the pipeline's deploy gate reads.
per_pair.csv contains reader ids: keep it in the private bucket, never commit it.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from twotower._evaluation import ensure_evaluation
from twotower.data import DataPaths
from twotower.recommender import TwoTower

ensure_evaluation()

from evaluation import models as team_models  # noqa: E402
from evaluation import run as team_run  # noqa: E402
from evaluation.aggregate import recommend_pair  # noqa: E402
from evaluation.data import likes, load_books, load_interactions  # noqa: E402
from evaluation.metrics import pair_metrics  # noqa: E402
from evaluation.pairs import sample_pairs  # noqa: E402
from evaluation.split import make_eval_readers, split_users  # noqa: E402

log = logging.getLogger(__name__)
K = 10
DEFAULT_MODELS = "popularity,item_knn,als,two_tower"


def train_and_tune(
    data: DataPaths, seed: int = 42, n_pairs: int = 300, aggregation: str = "average"
) -> tuple[pd.DataFrame, Callable[[Any], float]]:
    """The TRAIN interactions and a TUNE scorer (mean Min-Recall@10 over TUNE pairs).

    Same split and pair sampler as the evaluator, so TEST readers are never seen in training
    or early stopping.
    """
    inter = load_interactions(data.interactions)
    books = load_books(data.books)
    split = split_users(inter["user_id"], seed=seed)
    train = inter[inter["user_id"].isin(split.train)]
    catalogue = set(likes(train)["work_id"])
    tune_readers = make_eval_readers(inter, split.tune, catalogue, seed=seed)
    tune_pairs = sample_pairs(
        tune_readers, dict(zip(books["work_id"], books["genres"], strict=True)), n_pairs, seed=seed
    )

    def tune_fn(model: Any) -> float:
        vals = [
            float(
                pair_metrics(
                    recommend_pair(model, pr.a.favorites, pr.b.favorites, K, aggregation), pr.a.hidden, pr.b.hidden, K
                )["min_recall"]
                or 0.0
            )
            for pr in tune_pairs
        ]
        return float(sum(vals) / len(vals)) if vals else 0.0

    return train, tune_fn


def register(model: TwoTower) -> None:
    """The evaluator calls MODELS[name]().fit(train); hand it the already trained model."""

    class Prefit:
        name = "two_tower"

        def fit(self, _train: pd.DataFrame) -> TwoTower:
            return model

    team_models.MODELS["two_tower"] = Prefit


def evaluate(
    model: TwoTower,
    data: DataPaths,
    out: str | Path,
    *,
    models: str = DEFAULT_MODELS,
    seed: int = 42,
    n_pairs: int = 300,
    run_id: str = "test-eval",
) -> dict[str, Any]:
    """TEST-split evaluation with the team harness; returns the metrics.json content."""
    out = Path(out)
    register(model)
    args = team_run.parse_args(
        [
            "--interactions",
            str(data.interactions),
            "--books",
            str(data.books),
            "--out",
            str(out),
            "--run-id",
            run_id,
            "--split",
            "test",
            "--models",
            models,
            "--seed",
            str(seed),
            "--n-pairs",
            str(n_pairs),
        ]
    )
    run_dir = team_run.run(args)
    summary = pd.read_csv(run_dir / "summary.csv")
    head = summary[(summary.pair_kind == "all") & (summary.n_favorites == summary.n_favorites.max())]
    head = head[["model", "aggregation", "min_recall", "min_recall_ci95", "mean_ndcg", "long_tail_coverage"]]
    head.to_csv(out / "headline.csv", index=False)
    metrics: dict[str, Any] = {"split": "test", "k": K, "n_pairs": n_pairs, "seed": seed, "models": {}}
    for r in head.itertuples():
        metrics["models"].setdefault(r.model, {})[r.aggregation] = {
            "min_recall": float(r.min_recall),
            "min_recall_ci95": float(r.min_recall_ci95),
            "mean_ndcg": float(r.mean_ndcg),
            "long_tail_coverage": float(r.long_tail_coverage),
        }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    log.info("\n%s", head.to_string(index=False))
    return metrics


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True, help="folder with processed/ and embeddings/")
    ap.add_argument("--model-dir", required=True, help="a saved model folder (train.py writes <run>/model)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n-pairs", type=int, default=300)
    ap.add_argument("--device", default="auto")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    data = DataPaths(Path(a.data_dir))
    data.check()
    model = TwoTower.load(a.model_dir, device=a.device)
    evaluate(model, data, a.out, models=a.models, seed=a.seed, n_pairs=a.n_pairs)


if __name__ == "__main__":
    main()
