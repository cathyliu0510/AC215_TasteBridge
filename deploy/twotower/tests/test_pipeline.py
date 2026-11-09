"""Compile-time checks of the shared pipeline: no cloud access, no Docker."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline as pl  # noqa: E402

TT = "us-central1-docker.pkg.dev/tastebridge-511403/twotower/twotower-train@sha256:" + "a" * 64
ALS = "us-central1-docker.pkg.dev/tastebridge-511403/twotower/als-train@sha256:" + "b" * 64


def _compile(tmp_path: Path, model: str, **kwargs) -> tuple[str, dict]:
    out = pl.compile_pipeline(model, tmp_path / f"{model}.yaml", twotower_image=TT, **kwargs)
    text = out.read_text()
    return text, yaml.safe_load(text)


def test_twotower_branch_trains_on_a_t4_as_the_trainer(tmp_path: Path) -> None:
    text, spec = _compile(tmp_path, "twotower")
    tasks = spec["root"]["dag"]["tasks"]
    assert {"check-data", "train", "evaluate", "condition-1"} <= set(tasks)
    assert "worker_pool_specs" in text and "google_cloud_pipeline_components" in text  # train = a CustomJob
    assert "NVIDIA_TESLA_T4" in text and pl.SA in text
    assert "--no-evaluate" in text and "cuda" in text
    assert text.count(TT) >= 4  # check, train, evaluate, publish: one pinned image
    assert "{{$.pipeline_job_name}}" in text  # run id = the pipeline job's name


def test_gate_compares_least_misery_with_the_threshold(tmp_path: Path) -> None:
    _, spec = _compile(tmp_path, "twotower")
    gate = spec["root"]["dag"]["tasks"]["condition-1"]
    assert gate["taskInfo"]["name"] == "gate-least-misery"
    assert "min_recall_lm" in gate["triggerPolicy"]["condition"]
    assert ">=" in gate["triggerPolicy"]["condition"]
    assert spec["root"]["inputDefinitions"]["parameters"]["threshold"]["defaultValue"] == pl.THRESHOLD == 0.042
    assert "publish" in yaml.safe_dump(spec["components"]["comp-condition-1"])


def test_cpu_option_drops_the_gpu(tmp_path: Path) -> None:
    text, _ = _compile(tmp_path, "twotower", gpu=False)
    assert "NVIDIA_TESLA_T4" not in text and "--device" in text


def test_als_branch_uses_cathys_image_for_train_only(tmp_path: Path) -> None:
    text, _ = _compile(tmp_path, "als", als_image=ALS)
    assert text.count(ALS) == 1 and "NVIDIA_TESLA_T4" not in text
    assert "--no-evaluate" not in text  # only the shared interface is passed to the ALS image
    assert text.count(TT) >= 3  # the shared steps still run in the twotower image


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"model": "als"}, "needs --als-image"),
        ({"model": "bpr"}, "twotower or als"),
        ({"model": "twotower", "twotower_image": "repo/img:latest"}, "pin images by digest"),
    ],
)
def test_bad_inputs_are_refused(kwargs: dict, message: str) -> None:
    model = kwargs.pop("model")
    with pytest.raises(ValueError, match=message):
        pl.build_pipeline(model, **{"twotower_image": TT, **kwargs})


def test_cli_refuses_the_placeholder_image(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit):
        pl.main(["--out", str(tmp_path / "x.yaml")])
    assert "set TWOTOWER_IMAGE" in capsys.readouterr().err
