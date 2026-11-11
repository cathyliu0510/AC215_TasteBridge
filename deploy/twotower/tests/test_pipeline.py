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


def test_cli_compiles_with_the_pinned_default_image(tmp_path: Path) -> None:
    """`python pipeline.py` (no --run) only compiles; the default image is pinned by digest."""
    assert "@sha256:" in pl.TWOTOWER_IMAGE and "REPLACE_WITH" not in pl.TWOTOWER_IMAGE
    out = tmp_path / "x.yaml"
    assert pl.main(["--out", str(out)]) == 0
    assert pl.TWOTOWER_IMAGE in out.read_text()


def test_cli_refuses_a_placeholder_image(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit):
        pl.main(["--out", str(tmp_path / "x.yaml"), "--twotower-image", "img@sha256:REPLACE_WITH_DIGEST"])
    assert "set TWOTOWER_IMAGE" in capsys.readouterr().err


def test_run_id_reaches_the_gpu_train_step_as_a_resolved_value(tmp_path: Path) -> None:
    """Regression: the CustomJob wrapper doesn't resolve {{$.pipeline_job_name}}, so the first run
    trained into runs/{{$.pipeline_job_name}}/ and evaluate failed. Only check-data may see the raw
    placeholder; every other step must take run_id from check-data's output."""
    _, spec = _compile(tmp_path, "twotower")
    tasks = spec["root"]["dag"]["tasks"]
    assert tasks["check-data"]["inputs"]["parameters"]["job_name"]["runtimeValue"]["constant"] == (
        "{{$.pipeline_job_name}}"
    )
    from_check = {"taskOutputParameter": {"outputParameterKey": "run_id", "producerTask": "check-data"}}
    for name in ("train", "evaluate"):
        assert tasks[name]["inputs"]["parameters"]["run_id"] == from_check, name
    assert tasks["condition-1"]["inputs"]["parameters"]["pipelinechannel--check-data-run_id"] == from_check


@pytest.mark.parametrize("model", ["twotower", "als"])
def test_shared_pipeline_is_labelled_for_the_team(tmp_path: Path, model: str) -> None:
    text, _ = _compile(tmp_path, model, **({"als_image": ALS} if model == "als" else {}))
    assert "owner: team" in text and "owner: yitong" not in text


def test_submit_uses_only_supported_init_arguments(tmp_path: Path, monkeypatch) -> None:
    """aip.init() has no output_artifacts_gcs_dir (TypeError); submit must not pass it."""
    import inspect

    import google.cloud.aiplatform as aip

    accepted = set(inspect.signature(aip.init).parameters)
    seen: dict = {}

    def fake_init(**kwargs):
        assert set(kwargs) <= accepted, f"unsupported aip.init arguments: {set(kwargs) - accepted}"
        seen["init"] = kwargs

    class FakeJob:
        resource_name = "projects/p/locations/us-central1/pipelineJobs/x"

        def __init__(self, **kwargs):
            seen["job"] = kwargs

        def submit(self, service_account):
            seen["sa"] = service_account

    monkeypatch.setattr(aip, "init", fake_init)
    monkeypatch.setattr(aip, "PipelineJob", FakeJob)
    pl.submit(tmp_path / "t.yaml", "als", enable_caching=False, parameters={"threshold": 0.042})
    assert seen["init"] == {"project": pl.PROJECT, "location": pl.REGION}
    assert seen["job"]["pipeline_root"] == pl.DEFAULTS["pipeline_root"]
    assert seen["job"]["labels"] == {"owner": "team", "component": "pipeline-als"}
    assert seen["sa"] == pl.SA
