"""B2 ALS as the `train` step of the shared Vertex AI pipeline (deploy/twotower/pipeline.py).

Owner: Cathy Liu. The pipeline starts this image exactly like the M1 image (same interface):

    /docker-entrypoint.sh train --data-dir D --out R --run-id ID \
        [--wandb-entity E --wandb-secret S] [--als-factors ...]

    reads   D/processed/{books,interactions}.parquet + manifest.json
    writes  R/ID/model/{books.json, item_embeddings.npy, coords_2d.npy, meta.json}

The model is the unchanged MS2 exporter (evaluation.export): ALS refitted on all readers with the
tuned hyperparameters. Only three things change for the pipeline:
- model_version gets the run id (b2-als-<data_version>-<run_id>), so every run is a new version
  and the shared publish step, which never overwrites, can't collide with an earlier run;
- meta.json gets the MS3 contract keys `run_id` and `wandb_run_id`;
- the export is built on local disk and copied into R at the end, because R is a Cloud Storage
  FUSE mount (/gcs/...) where the exporter's rename-into-place isn't reliable.

W&B: ALS has no training curve worth tracking (15 closed-form ALS sweeps), so this step logs
nothing and sets wandb_run_id to null. The shared evaluate step then opens a new W&B run for the
ALS TEST metrics (deploy/twotower: "added ... to a new evaluation run (ALS)"). --wandb-entity and
--wandb-secret are accepted so the pipeline can call both images with the same arguments.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path

from evaluation.als import ALSParams
from evaluation.export import export

log = logging.getLogger("pipeline_train")

# meta.json is copied last: a model/ folder with a meta.json is a complete one.
CONTRACT_FILES = ("books.json", "item_embeddings.npy", "coords_2d.npy", "meta.json")


def train(data_dir: Path, out: Path, run_id: str, params: ALSParams) -> Path:
    """Fit + export B2 for one pipeline run; return the written <out>/<run_id>/model/ folder."""
    if not run_id or "/" in run_id or run_id in (".", ".."):
        raise ValueError(f"run id must be a plain folder name, got {run_id!r}")
    processed = data_dir / "processed"
    model_dir = out / run_id / "model"

    with tempfile.TemporaryDirectory(prefix="als-export-") as tmp:
        built = export(processed, Path(tmp), params)          # the MS2 exporter, unchanged
        meta = json.loads((built / "meta.json").read_text(encoding="utf-8"))
        meta.update(
            model_version=f"b2-als-{meta['data_version']}-{run_id}",
            run_id=run_id,
            wandb_run_id=None,                               # evaluate step opens the W&B run
            pipeline_step="train (model=als)",
        )
        (built / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        model_dir.mkdir(parents=True, exist_ok=True)
        for name in CONTRACT_FILES:
            shutil.copyfile(built / name, model_dir / name)

    log.info("Wrote %s (%d books) to %s", meta["model_version"], meta["counts"]["books"], model_dir)
    return model_dir


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Train + export B2 ALS for the shared pipeline.")
    p.add_argument("--data-dir", type=Path, required=True, help="folder holding processed/")
    p.add_argument("--out", type=Path, required=True, help="runs root; writes <out>/<run-id>/model/")
    p.add_argument("--run-id", required=True)
    # Same interface as the M1 image; ALS training itself is not tracked (see module docstring).
    p.add_argument("--wandb-entity", default=None)
    p.add_argument("--wandb-secret", default=None)
    # Defaults = the MS2 values tuned on the TUNE split (evaluation.als.ALSParams).
    p.add_argument("--als-factors", type=int, default=ALSParams.factors)
    p.add_argument("--als-reg", type=float, default=ALSParams.regularization)
    p.add_argument("--als-alpha", type=float, default=ALSParams.alpha)
    p.add_argument("--als-iterations", type=int, default=ALSParams.iterations)
    p.add_argument("--seed", type=int, default=ALSParams.seed)
    args = p.parse_args(argv)

    params = ALSParams(factors=args.als_factors, regularization=args.als_reg, alpha=args.als_alpha,
                       iterations=args.als_iterations, seed=args.seed)
    try:
        train(args.data_dir, args.out, args.run_id, params)
    except (FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
