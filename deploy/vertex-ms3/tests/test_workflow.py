"""Offline contract tests; fake table bytes and mocked children are not ML evidence."""
from __future__ import annotations

import base64
import copy
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

MODULE = Path(__file__).resolve().parents[1] / "workflow.py"
spec = importlib.util.spec_from_file_location("candidate_workflow", MODULE)
wf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wf)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ms3-offline-contract-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "source"
        for name in wf.source_files(wf.ROOT):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(wf.ROOT / name, target)
        self.processed = self.base / "processed"
        self.processed.mkdir()
        # Deliberately not parquet. Dry run checks bytes/provenance, not table validity.
        (self.processed / "books.parquet").write_bytes(b"synthetic-contract-fixture-books")
        (self.processed / "interactions.parquet").write_bytes(b"synthetic-contract-fixture-interactions")
        manifest = {"stage": "preprocess", "data_version": "synthetic-contract-fixture",
                    "input_kind": "synthetic", "inputs": {"mode": "synthetic"},
                    "files": {name: wf.sha256(self.processed / name) for name in wf.INPUTS[:2]}}
        wf.write_json(self.processed / "manifest.json", manifest)
        self.kwargs = dict(root=self.root, manifest=self.processed / "manifest.json",
                           base_commit="1" * 40, run_id="fixture-only-review",
                           processed_uri="gs://fixture-input-only/processed/synthetic-contract-fixture",
                           approval_reference="synthetic-contract-fixture-no-real-data",
                           project="review-project", region="us-central1",
                           image_uri="us-central1-docker.pkg.dev/review-project/fixture/worker@sha256:" + "2" * 64,
                           service_account="ms3-worker@review-project.iam.gserviceaccount.com",
                           output_uri="gs://fixture-output-only/offline-review")
        self.plan = wf.make_plan(**self.kwargs)
        self.out = self.base / "run"

    def run_worker(self, **kwargs):
        return wf.run_worker(self.plan, root=self.root, processed=self.processed, out=self.out, **kwargs)

    def receipt(self):
        return json.loads((self.out / "receipt.json").read_text())

    def fake_runner(self, command, **kwargs):
        """Create fixtures matching the existing modules' output contracts; never fit."""
        self.assertIs(kwargs["check"], False)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["env"]["WANDB_MODE"], "disabled")
        if command[2] == "evaluation.export":
            artifact = self.out / "artifacts/current"
            artifact.mkdir(parents=True)
            for name in wf.EXPORTS[:3]:
                (artifact / name).write_bytes(b"mocked-model-output-not-real-ML-evidence")
            wf.write_json(artifact / "meta.json", {
                "model_version": "b2-als-" + self.plan["input"]["data_version"],
                "data_version": self.plan["input"]["data_version"],
                "hyperparameters": self.plan["parameters"]["als"],
                "code_version": "source-sha256:" + self.plan["source"]["fingerprint_sha256"]})
        else:
            self.assertEqual(command[2], "evaluation.run")
            evdir = self.out / "evaluation/held-out"
            evdir.mkdir(parents=True)
            wf.write_json(evdir / "config.json", {
                "git_commit": "source-sha256:" + self.plan["source"]["fingerprint_sha256"],
                "arguments": {"synthetic": False, "als_factors": 128, "als_reg": 50.0, "als_alpha": 20.0,
                              "als_iterations": 15, "seed": 42, **wf.PARAMETERS["evaluation"]},
                "data": {"books": {"sha256": self.plan["input"]["files_sha256"]["books.parquet"]},
                         "interactions": {"sha256": self.plan["input"]["files_sha256"]["interactions.parquet"]}}})
            (evdir / "summary.md").write_text("MOCKED fixture aggregate results only.\n")
            with (evdir / "summary.csv").open("w", newline="") as handle:
                fields = ["model", "aggregation", "n_favorites", "pair_kind", "min_recall", "mean_ndcg", "long_tail_coverage"]
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for model in wf.PARAMETERS["evaluation"]["models"]:
                    for aggregation in wf.PARAMETERS["evaluation"]["aggregations"]:
                        writer.writerow(dict(model=model, aggregation=aggregation, n_favorites=5, pair_kind="all",
                                             min_recall=0.04, mean_ndcg=0.35, long_tail_coverage=0.05))
            (evdir / "per_pair.csv").write_text("PRIVATE_READER_LEVEL_SENTINEL\n")
            (evdir / "sample_recommendations.json").write_text('["PRIVATE_READER_LEVEL_SENTINEL"]')
        return SimpleNamespace(returncode=0)

    def assert_stopped(self, action, expected="failed"):
        with self.assertRaises((wf.CandidateError, OSError, subprocess.TimeoutExpired)):
            action()
        self.assertEqual(self.receipt()["status"], expected)
        self.assertFalse(self.receipt()["cloud_execution_verified"])

    def test_custom_job_is_immutable_single_cpu_worker_and_defaults_to_dry_run(self):
        request = wf.custom_job_request(self.plan)
        job = request["jobSpec"]
        self.assertEqual(job["serviceAccount"], self.kwargs["service_account"])
        self.assertEqual(job["scheduling"]["timeout"], "3600s")
        self.assertEqual(len(job["workerPoolSpecs"]), 1)
        worker = job["workerPoolSpecs"][0]
        self.assertEqual(worker["replicaCount"], "1")
        args = worker["containerSpec"]["args"]
        self.assertNotIn("--execute", args)
        self.assertNotIn("--persist-output", args)
        self.assertEqual(json.loads(base64.urlsafe_b64decode(args[2])), self.plan)
        self.assertTrue(worker["containerSpec"]["imageUri"].endswith("@sha256:" + "2" * 64))
        self.assertNotIn("network", job)

    def test_plan_and_run_clis_generate_and_validate_without_execution(self):
        package = self.base / "plan-package"
        argv = ["plan", "--out", str(package)]
        for key, value in self.kwargs.items():
            argv.extend(["--" + key.replace("_", "-"), str(value)])
        self.assertEqual(wf.main(argv), 0)
        self.assertTrue((package / "custom-job-request.json").is_file())
        review = json.loads((package / "review.json").read_text())
        self.assertIs(review["submitted"], False)
        self.assertEqual(wf.main(["run", "--plan", str(package / "plan.json"),
                                  "--root", str(self.root), "--processed", str(self.processed),
                                  "--out", str(self.out)]), 0)
        self.assertEqual(self.receipt()["status"], "dry_run_validated")

    def test_dry_run_verifies_hashes_but_never_executes(self):
        runner = Mock(side_effect=AssertionError("dry run executed a process"))
        receipt = self.run_worker(runner=runner)
        runner.assert_not_called()
        self.assertEqual(receipt["status"], "dry_run_validated")
        self.assertEqual(receipt["verified_inputs_sha256"], self.plan["input"]["files_sha256"])
        self.assertEqual(receipt["outputs_sha256"], {})
        self.assertFalse(receipt["external_tracking_verified"])
        self.assertFalse((self.out / "artifacts").exists())

    def test_export_and_evaluation_use_original_hyperparameters_and_split(self):
        steps = dict(wf.commands(self.plan, self.processed, self.out))
        for cmd in steps.values():
            for flag, value in (("--als-factors", "128"), ("--als-reg", "50.0"), ("--als-alpha", "20.0"),
                                ("--als-iterations", "15"), ("--seed", "42")):
                self.assertEqual(cmd[cmd.index(flag) + 1], value)
        self.assertEqual(steps["evaluate"][steps["evaluate"].index("--split") + 1], "test")
        self.assertNotIn("--synthetic", steps["evaluate"])

    def test_changed_input_fails_before_fitting(self):
        (self.processed / "books.parquet").write_bytes(b"changed")
        runner = Mock()
        self.assert_stopped(lambda: self.run_worker(execute=True, runner=runner))
        runner.assert_not_called()

    def test_missing_input_fails_before_fitting(self):
        (self.processed / "interactions.parquet").unlink()
        self.assert_stopped(lambda: self.run_worker())

    def test_input_file_symlink_is_rejected(self):
        book = self.processed / "books.parquet"
        other = self.base / "outside-books"
        book.rename(other)
        book.symlink_to(other)
        self.assert_stopped(lambda: self.run_worker())

    def test_input_directory_symlink_is_rejected(self):
        alias = self.base / "alias"
        alias.symlink_to(self.processed, target_is_directory=True)
        self.assert_stopped(lambda: wf.run_worker(self.plan, root=self.root, processed=alias, out=self.out))

    def test_source_tampering_stops_before_fitting(self):
        (self.root / "src/evaluation/evaluation/als.py").write_text("changed model")
        self.assert_stopped(lambda: self.run_worker())

    def test_environment_lock_tampering_stops_before_fitting(self):
        (self.root / "src/evaluation/uv.lock").write_text("changed dependency lock")
        self.assert_stopped(lambda: self.run_worker())

    def test_manifest_cannot_relabel_synthetic_input(self):
        self.plan["input"]["input_kind"] = "operator_supplied_processed"
        self.assert_stopped(lambda: self.run_worker())

    def test_old_run_is_never_overwritten(self):
        self.out.mkdir()
        sentinel = self.out / "keep"
        sentinel.write_text("existing")
        with self.assertRaises(wf.CandidateError):
            self.run_worker()
        self.assertEqual(sentinel.read_text(), "existing")
        self.assertEqual(list(self.out.iterdir()), [sentinel])

    def test_output_cannot_overlap_inputs_or_source(self):
        for out in (self.processed / "child", self.processed.parent,
                    self.root / "src/evaluation/new-output"):
            with self.subTest(out=out), self.assertRaises(wf.CandidateError):
                wf.run_worker(self.plan, root=self.root, processed=self.processed, out=out)

    def test_plan_refuses_modified_or_wrongly_typed_model_parameters(self):
        for value in (16, 128.0, "128"):
            plan = copy.deepcopy(self.plan)
            plan["parameters"]["als"]["factors"] = value
            with self.subTest(value=value), self.assertRaises(wf.CandidateError):
                wf.validate_plan(plan)

    def test_storage_paths_reject_credentials_queries_and_traversal(self):
        for uri in ("gs://bucket/data/../raw", "gs://user:secret@bucket/data", "gs://bucket/data?token=x",
                    "https://bucket/data", "gs://bucket//data", "gs://bucket/", "gs://bucket/data/"):
            with self.subTest(uri=uri), self.assertRaises(wf.CandidateError):
                wf.storage_path(uri)

    def test_mutable_image_tags_are_rejected(self):
        self.plan["vertex"]["image_uri"] = "us-central1-docker.pkg.dev/review-project/worker:latest"
        with self.assertRaises(wf.CandidateError):
            wf.custom_job_request(self.plan)

    def test_input_and_output_cloud_prefixes_are_disjoint(self):
        self.plan["vertex"]["output_uri"] = self.plan["input"]["processed_uri"] + "/overwrites-input"
        with self.assertRaises(wf.CandidateError):
            wf.validate_plan(self.plan)

    def test_tracker_or_cloud_success_claims_cannot_be_injected(self):
        self.plan["tracking"]["cloud_job_name"] = "pretend-completed-job"
        with self.assertRaises(wf.CandidateError):
            wf.validate_plan(self.plan)

    def test_unrecognized_fields_rejected_instead_of_serializing_secrets(self):
        self.plan["vertex"]["credentials"] = "DO_NOT_SERIALIZE"
        with self.assertRaises(wf.CandidateError):
            wf.validate_plan(self.plan)

    def test_export_failure_stops_evaluation_and_records_failure(self):
        runner = Mock(return_value=SimpleNamespace(returncode=9))
        self.assert_stopped(lambda: self.run_worker(execute=True, runner=runner))
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(self.receipt()["stages"][-1]["returncode"], 9)
        self.assertEqual(self.receipt()["outputs_sha256"], {})

    def test_timeout_produces_a_failed_receipt(self):
        runner = Mock(side_effect=subprocess.TimeoutExpired("PRIVATE_SENTINEL", 3600))
        self.assert_stopped(lambda: self.run_worker(execute=True, runner=runner))
        self.assertEqual(self.receipt()["failure_type"], "TimeoutExpired")
        self.assertNotIn("PRIVATE_SENTINEL", (self.out / "receipt.json").read_text())

    def test_interruption_is_not_success(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_worker(execute=True, runner=Mock(side_effect=KeyboardInterrupt))
        self.assertEqual(self.receipt()["status"], "interrupted")
        self.assertEqual(self.receipt()["stages"][-1]["status"], "interrupted")

    def test_mocked_success_has_hashes_aggregate_metrics_and_no_cloud_claim(self):
        runner = Mock(side_effect=self.fake_runner)
        receipt = self.run_worker(execute=True, runner=runner)
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(receipt["status"], "completed_local")
        self.assertEqual(len(receipt["outputs_sha256"]), 9)
        self.assertEqual(len(json.loads((self.out / "metrics.json").read_text())["metrics"]), 9)
        self.assertFalse(receipt["cloud_execution_verified"])
        self.assertFalse(receipt["external_tracking_verified"])
        self.assertNotIn("per_pair.csv", json.dumps(receipt["outputs_sha256"]))
        self.assertNotIn("sample_recommendations.json", json.dumps(receipt["outputs_sha256"]))

    def test_wrong_export_identity_fails(self):
        def runner(command, **kwargs):
            result = self.fake_runner(command, **kwargs)
            if command[2] == "evaluation.export":
                path = self.out / "artifacts/current/meta.json"
                meta = json.loads(path.read_text())
                meta["hyperparameters"]["factors"] = 16
                wf.write_json(path, meta)
            return result
        self.assert_stopped(lambda: self.run_worker(execute=True, runner=runner))

    def test_wrong_evaluation_inputs_fail(self):
        def runner(command, **kwargs):
            result = self.fake_runner(command, **kwargs)
            if command[2] == "evaluation.run":
                path = self.out / "evaluation/held-out/config.json"
                config = json.loads(path.read_text())
                config["data"]["books"]["sha256"] = "0" * 64
                wf.write_json(path, config)
            return result
        self.assert_stopped(lambda: self.run_worker(execute=True, runner=runner))

    def test_missing_or_wrong_evaluation_source_fails(self):
        for source in (None, "wrong-source"):
            self.out = self.base / ("missing-source" if source is None else "wrong-source")
            def runner(command, **kwargs):
                result = self.fake_runner(command, **kwargs)
                if command[2] == "evaluation.run":
                    path = self.out / "evaluation/held-out/config.json"
                    config = json.loads(path.read_text())
                    if source is None:
                        config.pop("git_commit")
                    else:
                        config["git_commit"] = source
                    wf.write_json(path, config)
                return result
            self.assert_stopped(lambda: self.run_worker(execute=True, runner=runner))

    def test_children_share_one_monotonic_budget_with_finalization_margin(self):
        elapsed = {"seconds": 0.0}
        timeouts = []
        def runner(command, **kwargs):
            timeouts.append(kwargs["timeout"])
            result = self.fake_runner(command, **kwargs)
            if command[2] == "evaluation.export":
                elapsed["seconds"] = 3470.0
            return result
        receipt = self.run_worker(execute=True, runner=runner, clock=lambda: elapsed["seconds"])
        self.assertEqual(timeouts, [3480.0, 10.0])
        self.assertEqual(receipt["budget"]["finalization_reserve_seconds"], 120)
        self.assertEqual(receipt["status"], "completed_local")

    def test_exhausted_training_budget_does_not_start_evaluation(self):
        elapsed = {"seconds": 0.0}
        calls = []
        def runner(command, **kwargs):
            calls.append(command[2])
            result = self.fake_runner(command, **kwargs)
            elapsed["seconds"] = 3481.0
            return result
        self.assert_stopped(lambda: self.run_worker(execute=True, runner=runner, clock=lambda: elapsed["seconds"]))
        self.assertEqual(calls, ["evaluation.export"])

    def test_terminal_receipt_margin_stops_overrun_before_final_success(self):
        elapsed = {"seconds": 0.0}
        def runner(command, **kwargs):
            result = self.fake_runner(command, **kwargs)
            if command[2] == "evaluation.run":
                elapsed["seconds"] = 3596.0
            return result
        self.assert_stopped(lambda: self.run_worker(execute=True, runner=runner, clock=lambda: elapsed["seconds"]))

    def test_incomplete_and_nonfinite_metrics_fail(self):
        for replacement in ("", "nan"):
            out = self.base / ("empty" if not replacement else "nonfinite")
            self.out = out
            def runner(command, **kwargs):
                result = self.fake_runner(command, **kwargs)
                if command[2] == "evaluation.run":
                    path = out / "evaluation/held-out/summary.csv"
                    text = path.read_text()
                    path.write_text(text.splitlines()[0] + "\n" if not replacement else text.replace("0.04", replacement))
                return result
            self.assert_stopped(lambda: self.run_worker(execute=True, runner=runner))

    def test_input_changed_while_running_is_not_success(self):
        def runner(command, **kwargs):
            result = self.fake_runner(command, **kwargs)
            if command[2] == "evaluation.run":
                (self.processed / "books.parquet").write_bytes(b"changed-during-run")
            return result
        self.assert_stopped(lambda: self.run_worker(execute=True, runner=runner))

    def test_dry_run_cannot_persist(self):
        with self.assertRaises(wf.CandidateError):
            self.run_worker(persist_output=True)
        self.assertFalse(self.out.exists())

    def test_persistence_copies_only_allowlist_and_writes_receipt_last(self):
        cloud_fixture = self.base / "mock-gcs"
        original_is_dir, original_storage_path = Path.is_dir, wf.storage_path
        def fake_is_dir(path):
            return True if str(path) == "/gcs" else original_is_dir(path)
        def fake_storage_path(uri):
            return cloud_fixture if uri == self.plan["vertex"]["output_uri"] else original_storage_path(uri)
        with patch.object(wf, "storage_path", side_effect=fake_storage_path), patch.object(Path, "is_dir", fake_is_dir):
            receipt = self.run_worker(execute=True, persist_output=True, runner=self.fake_runner)
        dest = cloud_fixture / self.plan["run_id"]
        self.assertEqual(receipt["status"], "completed_local")
        saved = json.loads((dest / "receipt.json").read_text())
        self.assertEqual(saved["persistence_status"], "copied_and_hash_verified")
        self.assertFalse(saved["cloud_execution_verified"])
        files = [p for p in dest.rglob("*") if p.is_file()]
        self.assertFalse(any(p.name in ("per_pair.csv", "sample_recommendations.json", "export.log", "evaluate.log") for p in files))
        self.assertFalse(any(b"PRIVATE_READER_LEVEL_SENTINEL" in p.read_bytes() for p in files))

    def test_partial_persistence_has_no_completion_receipt(self):
        cloud_fixture = self.base / "mock-gcs"
        original_is_dir, original_copy, original_storage_path = Path.is_dir, shutil.copyfile, wf.storage_path
        def fake_is_dir(path):
            return True if str(path) == "/gcs" else original_is_dir(path)
        def broken_copy(source, target):
            if Path(target).name == "item_embeddings.npy":
                raise OSError("simulated interrupted copy")
            return original_copy(source, target)
        def fake_storage_path(uri):
            return cloud_fixture if uri == self.plan["vertex"]["output_uri"] else original_storage_path(uri)
        with patch.object(wf, "storage_path", side_effect=fake_storage_path), patch.object(Path, "is_dir", fake_is_dir), \
                patch.object(shutil, "copyfile", broken_copy):
            self.assert_stopped(lambda: self.run_worker(execute=True, persist_output=True, runner=self.fake_runner))
        self.assertFalse((cloud_fixture / self.plan["run_id"] / "receipt.json").exists())

    def test_execution_uses_and_removes_a_verified_private_input_snapshot(self):
        snapshots = []
        def runner(command, **kwargs):
            if command[2] == "evaluation.export":
                snapshot = Path(command[command.index("--processed") + 1])
                self.assertNotEqual(snapshot, self.processed)
                self.assertEqual(wf.verify_inputs(self.plan, snapshot), self.plan["input"]["files_sha256"])
                snapshots.append(snapshot)
            return self.fake_runner(command, **kwargs)
        self.run_worker(execute=True, runner=runner)
        self.assertEqual(len(snapshots), 1)
        self.assertFalse(snapshots[0].exists())

    def test_context_contains_only_source_lockfiles_and_inventory(self):
        staged = self.base / "build-context"
        self.assertEqual(wf.main(["context", "--root", str(self.root), "--out", str(staged)]), 0)
        copied = {p.relative_to(staged).as_posix() for p in staged.rglob("*") if p.is_file()}
        self.assertEqual(copied, set(wf.source_files(self.root)) | {"source-files.sha256.json"})
        self.assertFalse(any("data/" in path or ".env" in path or ".git/" in path for path in copied))


if __name__ == "__main__":
    unittest.main()
