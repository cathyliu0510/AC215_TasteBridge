"""The shared pipeline steps that run inside this image (deploy/twotower/pipeline.py).

Each subcommand is one box of the Vertex AI pipeline. Every path comes in as an argument, and
every value the pipeline needs back is written to a file path the pipeline hands in (KFP's
OutputPath). So the same commands also run by hand, locally or in the container:

    python -m twotower.steps check-data --data-dir D --data-version-out F
    python -m twotower.steps evaluate   --model twotower|als --data-dir D --runs-dir R --run-id ID \
                                        --min-recall-lm-out F1 --min-recall-avg-out F2 [--wandb-secret S]
    python -m twotower.steps publish    --runs-dir R --run-id ID --models-dir M --model-version-out F

check-data  fails the pipeline early if an input is missing, or if the description vectors don't
            cover the catalogue; returns the data_version.
evaluate    scores the run on the TEST split with the unchanged team evaluator and returns the
            least-misery and average Min-Recall@10 for the gate. M1: the saved model is scored
            next to B0/B1/B2. ALS: the harness fits B0/B1/B2 itself, as in MS2. The metrics are
            added to the W&B run of the training step (M1) or to a new evaluation run (ALS).
publish     (only reached when the gate passes) checks the 4-file contract and copies the model
            to <models-dir>/<model_version>/; published versions are never overwritten.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd

from twotower.data import DataPaths
from twotower.evaluate import DEFAULT_MODELS, evaluate
from twotower.export import check_contract, publish
from twotower.recommender import TwoTower
from twotower.tracking import resolve_wandb_key

log = logging.getLogger("twotower.steps")

# Which evaluator row is "the model" for each pipeline branch, and which models to score with it.
BRANCHES = {
    "twotower": {"row": "two_tower", "models": DEFAULT_MODELS},
    "als": {"row": "als", "models": "popularity,item_knn,als"},
}


def _write(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(value), encoding="utf-8")


def check_data(data_dir: str | Path) -> str:
    data = DataPaths(Path(data_dir))
    data.check()  # raises FileNotFoundError naming every missing file
    version = data.version().get("data_version")
    if not version:
        raise ValueError(f"{data.processed / 'manifest.json'} has no data_version")
    books = pd.read_parquet(data.books, columns=["work_id"])
    rows = pd.read_parquet(data.desc_rows, columns=["work_id"])
    missing = set(books["work_id"].astype(str)) - set(rows["work_id"].astype(str))
    if missing:
        raise ValueError(f"{len(missing)} of {len(books)} books have no description vector, e.g. {sorted(missing)[:3]}")
    log.info("data %s OK: %d books, all with description vectors", version, len(books))
    return str(version)


def evaluate_run(
    model: str,
    data_dir: str | Path,
    run_dir: str | Path,
    *,
    seed: int = 42,
    n_pairs: int = 300,
    wandb_secret: str | None = None,
    wandb_entity: str | None = None,
    wandb_project: str | None = None,
) -> dict[str, float]:
    """TEST metrics for one branch; writes run_dir/headline.csv and metrics.json like train.py."""
    if model not in BRANCHES:
        raise ValueError(f"model must be one of {sorted(BRANCHES)}, got {model!r}")
    branch = BRANCHES[model]
    run_dir = Path(run_dir)
    data = DataPaths(Path(data_dir))
    m1 = TwoTower.load(run_dir / "model") if model == "twotower" else None
    metrics = evaluate(m1, data, run_dir, models=branch["models"], seed=seed, n_pairs=n_pairs)
    row = metrics["models"][branch["row"]]
    result = {
        "min_recall_lm": float(row["least_misery"]["min_recall"]),
        "min_recall_avg": float(row["average"]["min_recall"]),
    }
    log.info("%s TEST Min-Recall@10: least misery %.4f, average %.4f", model, *result.values())
    _log_to_wandb(model, run_dir, metrics, wandb_secret, wandb_entity, wandb_project)
    return result


def _log_to_wandb(
    model: str,
    run_dir: Path,
    metrics: dict[str, Any],
    secret: str | None,
    entity: str | None,
    project: str | None,
) -> None:
    """Add the TEST metrics to the training step's W&B run (M1), or to a new run (ALS)."""
    key = resolve_wandb_key(None, secret)
    if key is None and os.environ.get("WANDB_MODE") not in ("offline", "disabled"):
        log.info("no W&B key; TEST metrics are in %s only", run_dir / "metrics.json")
        return
    import wandb

    meta_path = run_dir / "model" / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    if key is not None:
        wandb.login(key=key)
    run = wandb.init(
        project=project or os.environ.get("WANDB_PROJECT", "tastebridge-two-tower"),
        entity=entity or os.environ.get("WANDB_ENTITY") or None,
        id=meta.get("wandb_run_id") or None,  # resume the training run when there is one
        resume="allow",
        name=run_dir.name,
        job_type="evaluate",
        dir="/tmp" if run_dir.as_posix().startswith("/gcs/") else str(run_dir),
    )
    run.summary.update(
        {
            f"test/{name}/{agg}/{key_}": value
            for name, aggs in metrics["models"].items()
            for agg, values in aggs.items()
            for key_, value in values.items()
        }
    )
    run.finish()


def publish_run(runs_dir: str | Path, run_id: str, models_dir: str | Path) -> str:
    model_dir = Path(runs_dir) / run_id / "model"
    meta = check_contract(model_dir)
    target = publish(model_dir, models_dir)
    log.info("published %s to %s", meta["model_version"], target)
    return str(meta["model_version"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check-data")
    c.add_argument("--data-dir", required=True)
    c.add_argument("--data-version-out", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--model", required=True, choices=sorted(BRANCHES))
    e.add_argument("--data-dir", required=True)
    e.add_argument("--runs-dir", required=True)
    e.add_argument("--run-id", required=True)
    e.add_argument("--min-recall-lm-out", required=True)
    e.add_argument("--min-recall-avg-out", required=True)
    e.add_argument("--seed", type=int, default=42)
    e.add_argument("--n-pairs", type=int, default=300)
    e.add_argument("--wandb-secret", default=None)
    e.add_argument("--wandb-entity", default=None)
    e.add_argument("--wandb-project", default=None)
    p = sub.add_parser("publish")
    p.add_argument("--runs-dir", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--models-dir", required=True)
    p.add_argument("--model-version-out", required=True)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if a.cmd == "check-data":
        _write(a.data_version_out, check_data(a.data_dir))
    elif a.cmd == "evaluate":
        res = evaluate_run(
            a.model,
            a.data_dir,
            Path(a.runs_dir) / a.run_id,
            seed=a.seed,
            n_pairs=a.n_pairs,
            wandb_secret=a.wandb_secret,
            wandb_entity=a.wandb_entity,
            wandb_project=a.wandb_project,
        )
        _write(a.min_recall_lm_out, res["min_recall_lm"])
        _write(a.min_recall_avg_out, res["min_recall_avg"])
    else:
        _write(a.model_version_out, publish_run(a.runs_dir, a.run_id, a.models_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
