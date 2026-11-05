#!/usr/bin/env python3
"""Produce fixture-only configuration and dry-run evidence; no ML or cloud action."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

import workflow as wf


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                            str(Path(__file__).parent / "tests"), "-v"],
                           cwd=wf.ROOT, capture_output=True, text=True, check=False)
    (out / "tests.log").write_text(tests.stdout + tests.stderr)
    count = re.search(r"Ran (\d+) tests?", tests.stderr)
    tests_count = int(count[1]) if count else 0
    result = {"status": "offline_checks_failed", "scope": "fixture-only configuration/provenance; no ML fit",
              "python": platform.python_version(), "at": wf.now(), "tests_exit_code": tests.returncode,
              "tests_count": tests_count,
              "training_executed": False, "cloud_api_calls": False, "image_built": False,
              "cloud_job_submitted": False, "online_tracking_run": False,
              "vertex_validation": "local expected-shape checks only; no cloud API validation"}
    if tests.returncode or not tests_count:
        wf.write_json(out / "verification.json", result)
        return 1
    fixture = out / "synthetic-invalid-parquet-fixture"
    fixture.mkdir()
    for name in wf.INPUTS[:2]:
        (fixture / name).write_bytes(b"FIXTURE ONLY, NOT PARQUET, NEVER TRAIN ON THIS: " + name.encode())
    wf.write_json(fixture / "manifest.json", {
        "stage": "preprocess", "data_version": "synthetic-invalid-parquet-fixture",
        "input_kind": "synthetic", "inputs": {"mode": "synthetic"},
        "files": {name: wf.sha256(fixture / name) for name in wf.INPUTS[:2]}})
    base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wf.ROOT,
                                 capture_output=True, text=True, check=True).stdout.strip()
    plan = wf.make_plan(root=wf.ROOT, manifest=fixture / "manifest.json", base_commit=base_commit,
                        run_id="fixture-only-offline-review",
                        processed_uri="gs://fixture-input-only/processed/synthetic-invalid-parquet-fixture",
                        approval_reference="fixture-only-no-data-access-approval",
                        project="review-project", region="us-central1",
                        image_uri="us-central1-docker.pkg.dev/review-project/fixture/worker@sha256:" + "2" * 64,
                        service_account="ms3-worker@review-project.iam.gserviceaccount.com",
                        output_uri="gs://fixture-output-only/offline-review")
    wf.write_json(out / "fixture-plan.json", plan)
    request = wf.custom_job_request(plan)
    wf.write_json(out / "fixture-custom-job-request.json", request)
    encoded = request["jobSpec"]["workerPoolSpecs"][0]["containerSpec"]["args"][2]
    assert json.loads(base64.urlsafe_b64decode(encoded)) == plan
    def forbidden_runner(*unused, **unused_kwargs):
        raise AssertionError("An offline dry run attempted to launch an ML subprocess")
    receipt = wf.run_worker(plan, root=wf.ROOT, processed=fixture,
                            out=out / "fixture-dry-run", runner=forbidden_runner)
    result.update(status="offline_configuration_and_dry_run_passed",
                  fixture_only=True, dry_run_status=receipt["status"],
                  parameters=plan["parameters"], parameters_sha256=plan["parameters_sha256"],
                  source=plan["source"],
                  fixture_inputs_sha256=plan["input"]["files_sha256"],
                  plan_sha256=wf.digest(plan),
                  evidence_sha256={name: wf.sha256(out / name) for name in
                                   ("tests.log", "fixture-plan.json", "fixture-custom-job-request.json")})
    wf.write_json(out / "verification.json", result)
    print("Offline fixture configuration and dry-run checks passed. No training, image or cloud action occurred.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
