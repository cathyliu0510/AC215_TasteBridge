import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import unquote

from tools.verify_local_integration import parse_args, reserve_output, synthetic_version, wait_for_service


class LocalEvidenceRunner(unittest.TestCase):
    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "keep.txt"
            marker.write_text("existing team work")
            with self.assertRaisesRegex(ValueError, "already exists"):
                reserve_output(Path(directory))
            self.assertEqual(marker.read_text(), "existing team work")

    def test_synthetic_export_identity_preserves_the_original_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps({"data_version": "gr-testhash", "counts": {"books": 12}}))
            value = synthetic_version(path)
            self.assertEqual(value["data_version"], "synthetic-testhash")
            self.assertEqual(value["preprocessor_data_version"], "gr-testhash")
            self.assertEqual(value["input_kind"], "synthetic")
            self.assertEqual(value["counts"], {"books": 12})

    def test_dead_service_fails_before_using_another_listener(self):
        class Failed:
            returncode = 2
            def poll(self):
                return self.returncode
        with self.assertRaisesRegex(RuntimeError, "exit 2"):
            wait_for_service(Failed(), "http://127.0.0.1:1/health")

    def test_input_origin_must_be_explicit(self):
        args = parse_args(["--synthetic", "--out", "new-run"])
        self.assertTrue(args.synthetic)
        self.assertIsNone(args.processed)
        args = parse_args(["--processed", "existing", "--out", "new-run"])
        self.assertFalse(args.synthetic)
        self.assertEqual(args.processed, Path("existing"))


class CatalogueIndependentSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[2] / "deploy/cloud-run/smoke.py"
        spec = importlib.util.spec_from_file_location("cloud_contract_smoke", source)
        cls.smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.smoke)

    def fake_read(self, base, path, data=None):
        if path == "/api/health":
            return {"status": "ok", "num_books": 20, "model_version": "synthetic-model"}
        if path == "/healthz":
            return {"status": "ok"}
        if path.startswith("/api/books/search?"):
            self.searches.append(path)
            return [{"book_id": "some-catalogue-match"}]
        if path.startswith("/api/books/"):
            return {"book_id": unquote(path.removeprefix("/api/books/")), "title": "Invented title"}
        if path == "/api/recommend":
            items = []
            for i in range(5):
                fit_a, fit_b = .9-i*.1, .5-i*.05
                score = min(fit_a, fit_b) if data["aggregation"] == "least_misery" else (fit_a+fit_b)/2
                items.append({"book": {"book_id": str(i)}, "score": score, "fit_a": fit_a, "fit_b": fit_b,
                              "position": {"x": i*.1, "y": i*.2}, "reasons": {
                                  "reader_a": {"seed_id": data["reader_a"][0]},
                                  "reader_b": {"seed_id": data["reader_b"][0]}}})
            if getattr(self, "bad_score", False):
                items[0]["score"] = -2
            return {"model_version": "synthetic-model", "aggregation": data["aggregation"],
                    "galaxy": {"bridges": [{"book_id": str(i), "x": i*.1, "y": i*.2} for i in range(5)]},
                    "recommendations": items}
        self.fail("Unexpected API call")

    def fake_request(self, base, path, data=None):
        if path == "/":
            return base + "/a/?api=1", b"TasteBridge"
        raise HTTPError(base + path, 404, "Not found", {}, None)

    def test_explicit_opaque_catalogue_ids_work_without_fixture_titles(self):
        self.searches = []
        with patch.object(self.smoke, "read_json", self.fake_read), patch.object(self.smoke, "request", self.fake_request):
            result = self.smoke.check("http://local.test", {"num_books": 20, "model_version": "synthetic-model", "tag": "local"},
                                      feedback=False, seed_ids=["opaque/A?", "other&book"])
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["recommendation_checks"]), 2)
        self.assertEqual(len(self.searches), 2)
        self.assertTrue(all("Invented" in query for query in self.searches))
        self.assertIsNone(result["feedback_event"])

    def test_duplicate_reader_ids_do_not_count_as_two_reader_integration(self):
        self.searches = []
        with patch.object(self.smoke, "read_json", self.fake_read), patch.object(self.smoke, "request", self.fake_request):
            with self.assertRaisesRegex(RuntimeError, "distinct"):
                self.smoke.check("http://local.test", {"num_books": 20, "model_version": "synthetic-model", "tag": "local"},
                                 feedback=False, seed_ids=["same", "same"])

    def test_a_responding_service_with_wrong_ranking_scores_fails_the_contract(self):
        self.searches, self.bad_score = [], True
        with patch.object(self.smoke, "read_json", self.fake_read), patch.object(self.smoke, "request", self.fake_request):
            with self.assertRaisesRegex(RuntimeError, "score/ordering"):
                self.smoke.check("http://local.test", {"num_books": 20, "model_version": "synthetic-model", "tag": "local"},
                                 feedback=False, seed_ids=["a", "b"])
