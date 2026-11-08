"""Train M1 on TRAIN readers, early-stop on TUNE pairs, save, then score TEST (the L13 "task.py").

    python -m twotower.train --data-dir DATA --out RUNS [--epochs 150] [--set tau=0.2 ...]

The same command runs on a laptop, in the container and as a Vertex AI CustomJob; only the
paths change (`/data` + `/runs` in the container, `/gcs/<bucket>/...` on Vertex).

Output, <out>/<run-id>/:
    config.json        every setting plus data lineage, git commit and library versions
    tracking.jsonl     one row per epoch (also sent to W&B when a key is available)
    checkpoints/last.pt  resumable state, written every --checkpoint-every epochs (--resume)
    model/             two_tower.pt, item_embeddings.npy, items.json, params.json
    test-eval/, headline.csv, metrics.json   from twotower.evaluate (skip with --no-evaluate)
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

import torch

from twotower.data import DataPaths
from twotower.evaluate import DEFAULT_MODELS, evaluate, train_and_tune
from twotower.model import TwoTowerParams
from twotower.recommender import TwoTower
from twotower.tracking import Tracker

log = logging.getLogger("twotower.train")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True, help="folder with processed/ and embeddings/")
    ap.add_argument("--out", required=True, help="runs folder; the run writes <out>/<run-id>/")
    ap.add_argument("--run-id", default=None, help="default: tt-<UTC timestamp>")
    ap.add_argument("--epochs", type=int, default=None, help="shortcut for --set epochs=N")
    ap.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="override any TwoTowerParams field, e.g. --set tau=0.2 --set readout=cls",
    )
    ap.add_argument("--seed", type=int, default=42, help="split, pairs and model seed")
    ap.add_argument("--device", default="auto", help="auto | cpu | cuda")
    ap.add_argument("--tune-pairs", type=int, default=300)
    ap.add_argument("--n-pairs", type=int, default=300, help="TEST pairs for the final evaluation")
    ap.add_argument("--models", default=DEFAULT_MODELS, help="models in the final TEST table")
    ap.add_argument("--no-evaluate", action="store_true", help="stop after saving the model (pipeline step)")
    ap.add_argument("--checkpoint-every", type=int, default=10)
    ap.add_argument("--resume", action="store_true", help="continue from <run>/checkpoints/last.pt")
    ap.add_argument("--tracker", default="auto", choices=("auto", "wandb", "off"))
    ap.add_argument("--wandb-project", default=None, help="default: $WANDB_PROJECT or tastebridge-two-tower")
    ap.add_argument("--wandb-entity", default=None, help="default: $WANDB_ENTITY or your personal entity")
    ap.add_argument("--wandb-key-file", default=None, help="file holding the W&B API key")
    ap.add_argument(
        "--wandb-secret",
        default=None,
        help="Secret Manager version holding the key: projects/P/secrets/S/versions/latest",
    )
    return ap.parse_args(argv)


def git_commit() -> str | None:
    if os.environ.get("GIT_COMMIT"):
        return os.environ["GIT_COMMIT"]  # baked in at image build time
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            cwd=Path(__file__).parent,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def environment() -> dict[str, Any]:
    cuda = torch.cuda.is_available()
    return {
        "git_commit": git_commit(),
        "image": os.environ.get("IMAGE_URI"),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "cuda_build": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0) if cuda else None,
        "vertex_job": os.environ.get("CLOUD_ML_JOB_ID"),
    }


def main(argv: list[str] | None = None) -> Path:
    a = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    data = DataPaths(Path(a.data_dir))
    data.check()
    params = TwoTowerParams(seed=a.seed, device=a.device).override(a.set)
    if a.epochs is not None:
        params.epochs = a.epochs
    run_id = a.run_id or time.strftime("tt-%Y%m%dT%H%M%SZ", time.gmtime())
    run_dir = Path(a.out) / run_id
    config = {
        "run_id": run_id,
        "params": params.as_dict(),
        "data": data.version(),
        "env": environment(),
        "args": {k: v for k, v in vars(a).items() if not k.startswith("wandb_key")},
    }
    log.info("run %s -> %s", run_id, run_dir)

    tracker = Tracker(
        run_dir,
        run_id,
        config,
        mode=a.tracker,
        project=a.wandb_project,
        entity=a.wandb_entity,
        key_file=a.wandb_key_file,
        secret=a.wandb_secret,
    )
    try:
        train, tune_fn = train_and_tune(data, seed=a.seed, n_pairs=a.tune_pairs)
        model = TwoTower(
            params,
            content_paths=data.content_paths(),
            tune_fn=tune_fn,
            log_fn=tracker.log,
            checkpoint_dir=run_dir / "checkpoints",
            checkpoint_every=a.checkpoint_every,
            resume=a.resume,
        )
        tic = time.perf_counter()
        model.fit(train)
        fit_s = round(time.perf_counter() - tic, 1)
        n_params = sum(p.numel() for p in model._require_net().parameters() if p.requires_grad)
        model_dir = model.save(run_dir / "model", {"fit_seconds": fit_s, "run_id": run_id, **data.version()})
        tracker.summary(
            {
                "fit_seconds": fit_s,
                "trainable_parameters": n_params,
                "best_tune/min_recall@10": model.best_tune,
                "epochs_run": model.history[-1]["epoch"] if model.history else 0,
                "missing_content_items": model.missing_content,
            }
        )
        tracker.artifact(model_dir, name="two-tower-model", kind="model", metadata={"run_id": run_id})
        log.info("fitted in %.1fs; model saved to %s", fit_s, model_dir)
        if not a.no_evaluate:
            metrics = evaluate(model, data, run_dir, models=a.models, seed=a.seed, n_pairs=a.n_pairs)
            tracker.summary(
                {
                    f"test/{m}/{agg}/min_recall@10": v["min_recall"]
                    for m, aggs in metrics["models"].items()
                    for agg, v in aggs.items()
                }
            )
            tracker.artifact(run_dir / "headline.csv", name="two-tower-headline", kind="evaluation")
    finally:
        tracker.finish()
    return run_dir


if __name__ == "__main__":
    main()
