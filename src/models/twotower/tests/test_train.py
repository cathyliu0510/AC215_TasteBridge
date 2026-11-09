"""Training behaviour: the smoke test, early stopping, resume, save/load, and the evaluator."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from twotower import TwoTower, TwoTowerParams
from twotower.data import DataPaths
from twotower.model import multi_positive_loss, training_logits
from twotower.recommender import sample_batches


def test_smoke_three_steps_reduce_the_loss(tiny_data, tiny_params) -> None:
    """L13 [19:33]: a few optimiser steps on one fixed batch must lower its loss."""
    data, inter = tiny_data
    tiny_params.dropout = tiny_params.id_dim_dropout = 0.0
    model = TwoTower(tiny_params, content_paths=data.content_paths()).prepare(inter)
    net = model._require_net()
    fav, pad, tr, tc = next(sample_batches(model._user_likes, tiny_params, np.random.default_rng(0)))
    opt = torch.optim.AdamW(net.parameters(), lr=1e-2)
    net.train()
    losses = []
    for _ in range(4):
        loss = multi_positive_loss(training_logits(net, fav, pad), tr, tc)
        losses.append(loss.item())
        opt.zero_grad()
        loss.backward()
        opt.step()
    assert all(np.isfinite(losses))
    assert losses[-1] < losses[0]


def test_batches_hold_out_targets_from_favourites(tiny_data, tiny_params) -> None:
    data, inter = tiny_data
    model = TwoTower(tiny_params, content_paths=data.content_paths()).prepare(inter)
    for fav, pad, tr, tc in sample_batches(model._user_likes, tiny_params, np.random.default_rng(1)):
        assert (~pad).sum(axis=1).min() >= 1
        for r in range(len(fav)):
            assert not set(fav[r][~pad[r]]) & set(tc[tr == r]), "a favourite must never be its own target"


def test_fit_logs_every_epoch_and_early_stops(tiny_data, tiny_params) -> None:
    data, inter = tiny_data
    scores = iter([0.5, 0.4, 0.3, 0.2, 0.1])
    rows: list[dict] = []
    tiny_params.epochs, tiny_params.patience = 10, 2
    model = TwoTower(
        tiny_params, content_paths=data.content_paths(), tune_fn=lambda m: next(scores), log_fn=rows.append
    ).fit(inter)
    assert [r["epoch"] for r in rows] == [1, 2, 3], "stops after `patience` evaluations without gain"
    assert rows[0]["best"] is True and model.best_tune == 0.5
    assert all(np.isfinite(r["train/loss"]) for r in rows)


def test_resume_continues_exactly(tiny_data, tiny_params, tmp_path: Path) -> None:
    """Kill a run after epoch 3, resume from the epoch-2 checkpoint: same weights as uninterrupted."""
    data, inter = tiny_data
    tiny_params.epochs = 4
    straight = TwoTower(tiny_params, content_paths=data.content_paths(), log_fn=lambda r: None).fit(inter)

    class PreemptedError(Exception):
        pass

    def crash_at_3(row: dict) -> None:
        if row["epoch"] == 3:
            raise PreemptedError

    ckpt = tmp_path / "ckpt"
    with pytest.raises(PreemptedError):
        TwoTower(
            tiny_params, content_paths=data.content_paths(), log_fn=crash_at_3, checkpoint_dir=ckpt, checkpoint_every=2
        ).fit(inter)
    assert (ckpt / "last.pt").exists()
    resumed = TwoTower(
        tiny_params,
        content_paths=data.content_paths(),
        log_fn=lambda r: None,
        checkpoint_dir=ckpt,
        checkpoint_every=2,
        resume=True,
    ).fit(inter)
    assert [r["epoch"] for r in resumed.history] == [1, 2, 3, 4]
    for (k, a), b in zip(
        straight._require_net().state_dict().items(), resumed._require_net().state_dict().values(), strict=True
    ):
        torch.testing.assert_close(a, b, msg=k)


def test_save_and_load_round_trip(tiny_data, tiny_params, tmp_path: Path) -> None:
    data, inter = tiny_data
    tiny_params.epochs = 1
    model = TwoTower(tiny_params, content_paths=data.content_paths(), log_fn=lambda r: None).fit(inter)
    out = model.save(tmp_path / "model", {"note": "x"})
    loaded = TwoTower.load(out, device="cpu")
    assert loaded.items == model.items and loaded.p == model.p
    np.testing.assert_allclose(loaded.score(["w01", "w02"]), model.score(["w01", "w02"]), rtol=1e-6)
    assert not (out / "item_embeddings.npy").exists()  # written by twotower.export, in catalogue order
    assert json.loads((out / "params.json").read_text())["note"] == "x"


def test_evaluator_runs_with_two_tower_registered(synthetic_data: DataPaths, tmp_path: Path) -> None:
    """Integration: the team harness, unchanged, with M1 registered like any baseline."""
    from evaluation import models as team_models
    from evaluation import run as team_run

    params = TwoTowerParams(dim=16, layers=1, heads=2, ffn=32, epochs=2, batch_size=64, device="cpu")
    team_models.MODELS["two_tower"] = lambda: TwoTower(  # type: ignore[assignment]
        params, content_paths=synthetic_data.content_paths(), log_fn=lambda r: None
    )
    try:
        args = team_run.parse_args(
            [
                "--interactions",
                str(synthetic_data.interactions),
                "--books",
                str(synthetic_data.books),
                "--out",
                str(tmp_path / "res"),
                "--run-id",
                "it",
                "--models",
                "popularity,two_tower",
                "--n-pairs",
                "20",
            ]
        )
        run_dir = team_run.run(args)
    finally:
        team_models.MODELS.pop("two_tower", None)
    summary = pd.read_csv(run_dir / "summary.csv")
    assert {"popularity", "two_tower"} <= set(summary["model"])
    assert summary["min_recall"].between(0, 1).all()


def test_train_cli_end_to_end(synthetic_data: DataPaths, tmp_path: Path) -> None:
    """`python -m twotower.train` then `python -m twotower.evaluate` on the saved model."""
    from twotower import evaluate as tt_evaluate
    from twotower import train as tt_train

    common = ["--n-pairs", "20", "--models", "popularity,two_tower"]
    run_dir = tt_train.main(
        [
            "--data-dir",
            str(synthetic_data.root),
            "--out",
            str(tmp_path / "runs"),
            "--run-id",
            "cli",
            "--epochs",
            "2",
            "--tune-pairs",
            "20",
            "--tracker",
            "off",
            "--device",
            "cpu",
            "--set",
            "dim=16",
            "--set",
            "layers=1",
            "--set",
            "heads=2",
            "--set",
            "ffn=32",
            "--set",
            "eval_every=1",
            *common,
        ]
    )
    for name in (
        "config.json",
        "tracking.jsonl",
        "summary.json",
        "headline.csv",
        "metrics.json",
        "model/two_tower.pt",
        "model/items.json",
        "model/books.json",
        "model/item_embeddings.npy",
        "model/coords_2d.npy",
        "model/meta.json",
        "checkpoints/last.pt",
        "test-eval/summary.csv",
    ):
        assert (run_dir / name).exists(), name
    from twotower.export import check_contract

    meta = check_contract(run_dir / "model")  # the interface both pipeline train images must meet
    assert meta["run_id"] == "cli" and meta["wandb_run_id"] is None  # --tracker off
    assert meta["model_version"] == f"m1-tt-{meta['data_version']}-cli"
    rows = [json.loads(line) for line in (run_dir / "tracking.jsonl").read_text().splitlines()]
    assert [r["epoch"] for r in rows] == [1, 2] and "tune/min_recall@10" in rows[-1]
    config = json.loads((run_dir / "config.json").read_text())
    assert config["params"]["dim"] == 16 and config["params"]["epochs"] == 2
    trained = json.loads((run_dir / "metrics.json").read_text())

    tt_evaluate.main(
        [
            "--data-dir",
            str(synthetic_data.root),
            "--model-dir",
            str(run_dir / "model"),
            "--out",
            str(tmp_path / "re-eval"),
            "--device",
            "cpu",
            *common,
        ]
    )
    again = json.loads((tmp_path / "re-eval" / "metrics.json").read_text())
    for agg, values in trained["models"]["two_tower"].items():
        assert again["models"]["two_tower"][agg] == pytest.approx(values), agg


def test_check_device_fails_fast_when_a_gpu_is_requested_but_missing(monkeypatch, caplog) -> None:
    """Vertex job 6137552598636429312 asked for a T4 but trained on the CPU: `cuda` must stop at once."""
    from twotower.train import check_device

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="torch sees no GPU"):
        check_device("cuda")
    with caplog.at_level("INFO", logger="twotower.train"):
        assert check_device("auto").type == "cpu"  # auto still falls back, but says so
        assert check_device("cpu").type == "cpu"
    assert "device: cpu (CUDA available: False)" in caplog.text


def test_train_cli_stops_before_any_work_without_the_gpu(synthetic_data, tmp_path: Path, monkeypatch) -> None:
    from twotower import train as tt_train

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="--device cuda was requested"):
        tt_train.main(["--data-dir", str(synthetic_data.root), "--out", str(tmp_path / "runs"), "--device", "cuda"])
    assert not (tmp_path / "runs").exists()  # nothing written, no W&B run started
