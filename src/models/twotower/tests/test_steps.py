"""The shared pipeline steps (twotower.steps), run exactly as the pipeline calls them."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from twotower.data import DataPaths
from twotower.steps import main as steps

TINY = ["--set", "dim=16", "--set", "layers=1", "--set", "heads=2", "--set", "ffn=32", "--set", "eval_every=1"]


@pytest.fixture(autouse=True)
def _no_wandb(monkeypatch) -> None:
    """Tests never contact W&B: no key anywhere."""
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.delenv("WANDB_MODE", raising=False)


def _with_manifest(data: DataPaths, version: str = "gr-test") -> DataPaths:
    (data.processed / "manifest.json").write_text(json.dumps({"data_version": version}))
    return data


@pytest.fixture
def trained_run(synthetic_data: DataPaths, tmp_path: Path) -> tuple[DataPaths, Path, str]:
    """What the pipeline's train step leaves behind: train.py with --no-evaluate."""
    from twotower import train as tt_train

    data = _with_manifest(synthetic_data)
    runs = tmp_path / "runs"
    tt_train.main(
        ["--data-dir", str(data.root), "--out", str(runs), "--run-id", "pl-1", "--epochs", "2"]
        + ["--tune-pairs", "20", "--tracker", "off", "--device", "cpu", "--no-evaluate", *TINY]
    )
    return data, runs, "pl-1"


def test_check_data_returns_the_data_version(synthetic_data: DataPaths, tmp_path: Path) -> None:
    data = _with_manifest(synthetic_data, "gr-abc")
    out = tmp_path / "out" / "data_version"
    assert steps(["check-data", "--data-dir", str(data.root), "--data-version-out", str(out)]) == 0
    assert out.read_text() == "gr-abc"


def test_check_data_fails_on_missing_inputs(synthetic_data: DataPaths, tmp_path: Path) -> None:
    data = _with_manifest(synthetic_data)
    data.desc_embeddings.unlink()
    with pytest.raises(FileNotFoundError, match="desc_embeddings.npy"):
        steps(["check-data", "--data-dir", str(data.root), "--data-version-out", str(tmp_path / "v")])


def test_check_data_fails_when_vectors_dont_cover_the_catalogue(synthetic_data: DataPaths, tmp_path: Path) -> None:
    data = _with_manifest(synthetic_data)
    rows = pd.read_parquet(data.desc_rows)
    rows.iloc[1:].to_parquet(data.desc_rows)  # drop one book's description vector
    with pytest.raises(ValueError, match="1 of 120 books have no description vector"):
        steps(["check-data", "--data-dir", str(data.root), "--data-version-out", str(tmp_path / "v")])


def test_check_data_needs_a_data_version(synthetic_data: DataPaths, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no data_version"):
        steps(["check-data", "--data-dir", str(synthetic_data.root), "--data-version-out", str(tmp_path / "v")])


def _evaluate(model: str, data: DataPaths, runs: Path, run_id: str, out: Path) -> tuple[float, float]:
    args = ["evaluate", "--model", model, "--data-dir", str(data.root), "--runs-dir", str(runs), "--run-id", run_id]
    args += ["--min-recall-lm-out", str(out / "lm"), "--min-recall-avg-out", str(out / "avg"), "--n-pairs", "20"]
    assert steps(args) == 0
    return float((out / "lm").read_text()), float((out / "avg").read_text())


def test_evaluate_twotower_scores_the_saved_model(trained_run, tmp_path: Path) -> None:
    data, runs, run_id = trained_run
    assert not (runs / run_id / "metrics.json").exists()  # --no-evaluate: the pipeline scores it
    lm, avg = _evaluate("twotower", data, runs, run_id, tmp_path / "out")
    metrics = json.loads((runs / run_id / "metrics.json").read_text())
    assert lm == metrics["models"]["two_tower"]["least_misery"]["min_recall"]
    assert avg == metrics["models"]["two_tower"]["average"]["min_recall"]
    assert {"popularity", "item_knn", "als", "two_tower"} <= set(metrics["models"])  # baselines alongside
    assert 0 <= lm <= 1 and (runs / run_id / "headline.csv").exists()


def test_evaluate_als_branch_needs_no_m1_model(synthetic_data: DataPaths, tmp_path: Path) -> None:
    data = _with_manifest(synthetic_data)
    runs = tmp_path / "runs"
    (runs / "als-1").mkdir(parents=True)
    lm, _ = _evaluate("als", data, runs, "als-1", tmp_path / "out")
    metrics = json.loads((runs / "als-1" / "metrics.json").read_text())
    assert set(metrics["models"]) == {"popularity", "item_knn", "als"}
    assert lm == metrics["models"]["als"]["least_misery"]["min_recall"]


def test_publish_after_the_gate(trained_run, tmp_path: Path) -> None:
    _, runs, run_id = trained_run
    models = tmp_path / "models"
    out = tmp_path / "out" / "model_version"
    args = ["publish", "--runs-dir", str(runs), "--run-id", run_id, "--models-dir", str(models)]
    assert steps([*args, "--model-version-out", str(out)]) == 0
    version = out.read_text()
    assert version == "m1-tt-gr-test-pl-1" and (models / version / "meta.json").exists()
    with pytest.raises(FileExistsError):
        steps([*args, "--model-version-out", str(out)])  # a published version is never overwritten
