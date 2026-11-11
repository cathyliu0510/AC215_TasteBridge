"""Tests for the ALS pipeline train step (pipeline_train.py). Invented data only."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from evaluation import synthetic
from evaluation.als import ALSParams
from evaluation.pipeline_train import CONTRACT_FILES, main, train

FAST = ALSParams(factors=8, regularization=1.0, alpha=10.0, iterations=5, seed=0)
# The keys the shared contract check requires (src/models/twotower/twotower/export.py REQUIRED_META)
REQUIRED_META = ("model_version", "data_version", "wandb_run_id")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """<data-dir>/processed/ in the preprocess output format, as the pipeline mounts it."""
    inter, books = synthetic.generate(seed=1)
    folder = tmp_path / "data" / "processed"
    folder.mkdir(parents=True)
    inter["is_read"] = True
    inter.to_parquet(folder / "interactions.parquet", index=False)
    books = books.assign(
        title="Book " + books["work_id"].astype(str),
        author="Invented Author",
        year=pd.array([2001] * len(books), dtype="Int64"),
        shelves=[["fantasy", "heist"]] * len(books),
    )
    books.to_parquet(folder / "books.parquet", index=False)
    (folder / "manifest.json").write_text(json.dumps({"data_version": "gr-test123"}))
    return folder.parent


def test_train_writes_the_shared_contract(data_dir: Path, tmp_path: Path) -> None:
    model_dir = train(data_dir, tmp_path / "runs", "job-1", FAST)
    assert model_dir == tmp_path / "runs" / "job-1" / "model"
    assert sorted(p.name for p in model_dir.iterdir()) == sorted(CONTRACT_FILES)

    books = json.loads((model_dir / "books.json").read_text())
    emb = np.load(model_dir / "item_embeddings.npy")
    coords = np.load(model_dir / "coords_2d.npy")
    meta = json.loads((model_dir / "meta.json").read_text())
    assert len(books) == emb.shape[0] == coords.shape[0] > 0
    assert emb.dtype == np.float32 and coords.dtype == np.float32
    assert np.allclose(np.linalg.norm(emb, axis=1), 1.0, atol=1e-3)
    for key in REQUIRED_META:
        assert key in meta
    assert meta["model_version"] == "b2-als-gr-test123-job-1"
    assert meta["data_version"] == "gr-test123"
    assert meta["run_id"] == "job-1" and meta["wandb_run_id"] is None


def test_each_run_gets_its_own_model_version(data_dir: Path, tmp_path: Path) -> None:
    versions = {
        json.loads((train(data_dir, tmp_path / "runs", rid, FAST) / "meta.json").read_text())["model_version"]
        for rid in ("job-1", "job-2")
    }
    assert versions == {"b2-als-gr-test123-job-1", "b2-als-gr-test123-job-2"}


def test_cli_accepts_the_pipeline_arguments(data_dir: Path, tmp_path: Path) -> None:
    code = main([
        "--data-dir", str(data_dir), "--out", str(tmp_path / "runs"), "--run-id", "job-cli",
        "--wandb-entity", "TasteBridge", "--wandb-secret", "projects/p/secrets/s/versions/latest",
        "--als-factors", "8", "--als-iterations", "3",
    ])
    assert code == 0
    assert (tmp_path / "runs" / "job-cli" / "model" / "meta.json").is_file()


def test_cli_reports_missing_input_and_bad_run_id(tmp_path: Path, data_dir: Path) -> None:
    assert main(["--data-dir", str(tmp_path / "nope"), "--out", str(tmp_path / "runs"), "--run-id", "x"]) == 1
    assert main(["--data-dir", str(data_dir), "--out", str(tmp_path / "runs"), "--run-id", "a/b"]) == 1
