"""Tracking never needs the network in tests: JSONL always, W&B only in `disabled` mode."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from twotower.tracking import Tracker, resolve_wandb_key


@pytest.fixture(autouse=True)
def no_wandb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("WANDB_API_KEY", "WANDB_MODE", "WANDB_PROJECT", "WANDB_ENTITY"):
        monkeypatch.delenv(var, raising=False)


def test_off_mode_writes_config_and_jsonl(tmp_path: Path) -> None:
    t = Tracker(tmp_path / "run", "r1", {"lr": 1e-3}, mode="off")
    t.log({"epoch": 1, "step": 3, "train/loss": 2.5})
    t.summary({"fit_seconds": 1.0})
    t.artifact(tmp_path, name="m", kind="model")  # no-op without W&B
    t.finish()
    assert json.loads((tmp_path / "run" / "config.json").read_text()) == {"lr": 1e-3}
    assert json.loads((tmp_path / "run" / "tracking.jsonl").read_text()) == {"epoch": 1, "step": 3, "train/loss": 2.5}
    assert json.loads((tmp_path / "run" / "summary.json").read_text()) == {"fit_seconds": 1.0}


def test_auto_without_a_key_falls_back_to_jsonl(tmp_path: Path) -> None:
    t = Tracker(tmp_path, "r", {}, mode="auto")
    assert t.run is None and t.url is None
    t.finish()


def test_wandb_mode_without_a_key_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no W&B key"):
        Tracker(tmp_path, "r", {}, mode="wandb")


def test_key_lookup_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_file = tmp_path / "wandb.key"
    key_file.write_text("from-file\n")
    assert resolve_wandb_key() is None
    assert resolve_wandb_key(str(key_file)) == "from-file"
    monkeypatch.setenv("WANDB_API_KEY", "from-env")
    assert resolve_wandb_key(str(key_file)) == "from-env"


def test_wandb_code_path_in_disabled_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercises init -> log -> summary -> artifact -> finish without a key or network."""
    monkeypatch.setenv("WANDB_MODE", "disabled")
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "params.json").write_text("{}")
    t = Tracker(tmp_path / "run", "r", {"dim": 16}, mode="wandb")
    assert t.run is not None
    t.log({"epoch": 1, "step": 1, "train/loss": 1.0})
    t.summary({"best": 0.1})
    t.artifact(tmp_path / "model", name="two-tower-model", kind="model")
    t.finish()
    assert (tmp_path / "run" / "tracking.jsonl").exists()
