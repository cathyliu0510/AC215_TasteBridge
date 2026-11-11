import copy
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

    def setUp(self):
        self.release = {"num_books": 20, "model_version": "synthetic-model", "tag": "local",
                        "artifact_sha256": {"books.json": "1" * 64, "item_embeddings.npy": "2" * 64,
                                            "coords_2d.npy": "3" * 64, "meta.json": "4" * 64},
                        "data_version": "synthetic-data"}
        # Reference fingerprint for this four-file hash map, shared by health and recommendations.
        self.fingerprint = "14456c5a44acbe7f31c70d956e2aafabddae8e929a21d560ddf1e0751c421fb0"
        self.health = {"status": "ok", "num_books": 20, "model_version": "synthetic-model",
                       "artifact_fingerprint": self.fingerprint, "data_version": "synthetic-data"}
        self.searches = []

    def fake_read(self, base, path, data=None):
        if path == "/api/health":
            return dict(self.health)
        if path == "/frontend/health":
            return {"status": "ok", "service": "frontend"}
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
            if getattr(self, "rounded_score", False) and data["aggregation"] == "average":
                items[0].update(fit_a=.9001, fit_b=.5, score=.7)
            fingerprint = "0" * 64 if data["aggregation"] == getattr(self, "wrong_artifact_mode", None) else self.fingerprint
            response = {"model_version": "synthetic-model", "artifact_fingerprint": fingerprint, "aggregation": data["aggregation"],
                        "galaxy": {"bridges": [{"book_id": str(i), "x": i*.1, "y": i*.2} for i in range(5)]},
                        "recommendations": items}
            if data['aggregation'] == getattr(self, 'missing_artifact_mode', None):
                response.pop('artifact_fingerprint')
            return response
        self.fail("Unexpected API call")

    def fake_request(self, base, path, data=None):
        if path == "/":
            return base + "/a/?api=1", b"TasteBridge"
        raise HTTPError(base + path, 404, "Not found", {}, None)

    def test_explicit_opaque_catalogue_ids_work_without_fixture_titles(self):
        self.searches = []
        with patch.object(self.smoke, "read_json", self.fake_read), patch.object(self.smoke, "request", self.fake_request):
            result = self.smoke.check("http://local.test", self.release,
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
                self.smoke.check("http://local.test", self.release,
                                 feedback=False, seed_ids=["same", "same"])

    def test_a_responding_service_with_wrong_ranking_scores_fails_the_contract(self):
        self.searches, self.bad_score = [], True
        with patch.object(self.smoke, "read_json", self.fake_read), patch.object(self.smoke, "request", self.fake_request):
            with self.assertRaisesRegex(RuntimeError, "score/ordering"):
                self.smoke.check("http://local.test", self.release,
                                 feedback=False, seed_ids=["a", "b"])

    def test_valid_four_decimal_api_serialization_is_accepted(self):
        self.searches, self.rounded_score = [], True
        with patch.object(self.smoke, "read_json", self.fake_read), patch.object(self.smoke, "request", self.fake_request):
            result = self.smoke.check("http://local.test", self.release,
                                      feedback=False, seed_ids=["a", "b"])
        self.assertTrue(result["passed"])

    def test_same_name_and_count_cannot_hide_a_different_or_missing_artifact(self):
        for fingerprint in ("0" * 64, None):
            with self.subTest(fingerprint=fingerprint):
                self.health['artifact_fingerprint'] = fingerprint
                with patch.object(self.smoke, 'read_json', self.fake_read), patch.object(self.smoke, 'request') as request:
                    with self.assertRaisesRegex(RuntimeError, 'artifact fingerprint'):
                        self.smoke.check('http://local.test', self.release, feedback=True)
                request.assert_not_called()
        self.health.pop('artifact_fingerprint')
        with patch.object(self.smoke, 'read_json', self.fake_read), patch.object(self.smoke, 'request') as request:
            with self.assertRaisesRegex(RuntimeError, 'artifact fingerprint'):
                self.smoke.check('http://local.test', self.release, feedback=True)
        request.assert_not_called()

    def test_wrong_or_missing_data_version_stops_before_further_requests(self):
        for version in ('another-data-snapshot', None):
            with self.subTest(data_version=version):
                self.health['data_version'] = version
                with patch.object(self.smoke, 'read_json', self.fake_read), patch.object(self.smoke, 'request') as request:
                    with self.assertRaisesRegex(RuntimeError, 'data_version'):
                        self.smoke.check('http://local.test', self.release, feedback=True)
                request.assert_not_called()
        self.health.pop('data_version')
        with patch.object(self.smoke, 'read_json', self.fake_read), patch.object(self.smoke, 'request') as request:
            with self.assertRaisesRegex(RuntimeError, 'data_version'):
                self.smoke.check('http://local.test', self.release, feedback=True)
        request.assert_not_called()

    def test_missing_or_invalid_expected_identity_stops_before_http(self):
        candidates = []
        for field in ('artifact_sha256', 'data_version'):
            release = copy.deepcopy(self.release)
            release.pop(field)
            candidates.append(release)
        for hashes in ({}, {'books.json': '1' * 64},
                       {**self.release['artifact_sha256'], 'unexpected.json': 'a' * 64},
                       {**self.release['artifact_sha256'], 'meta.json': 'not-a-hash'}):
            candidates.append({**self.release, 'artifact_sha256': hashes})
        for release in candidates:
            with self.subTest(release=release), patch.object(self.smoke, 'read_json') as read, patch.object(self.smoke, 'request') as request:
                with self.assertRaisesRegex(RuntimeError, 'Release needs'):
                    self.smoke.check('http://local.test', release, feedback=True)
                read.assert_not_called()
                request.assert_not_called()

    def test_each_recommendation_mode_must_match_the_expected_artifact(self):
        for mode in ('least_misery', 'average'):
            with self.subTest(mode=mode):
                self.wrong_artifact_mode = mode
                with patch.object(self.smoke, 'read_json', self.fake_read), patch.object(self.smoke, 'request', self.fake_request):
                    with self.assertRaisesRegex(RuntimeError, 'Recommendation artifact fingerprint'):
                        self.smoke.check('http://local.test', self.release, feedback=False, seed_ids=['a', 'b'])

    def test_each_recommendation_mode_rejects_a_missing_artifact_identity(self):
        for mode in ('least_misery', 'average'):
            with self.subTest(mode=mode):
                self.missing_artifact_mode = mode
                with patch.object(self.smoke, 'read_json', self.fake_read), patch.object(self.smoke, 'request', self.fake_request):
                    with self.assertRaisesRegex(RuntimeError, 'Recommendation artifact fingerprint'):
                        self.smoke.check('http://local.test', self.release, feedback=False, seed_ids=['a', 'b'])

    def test_unrecorded_data_version_must_be_explicit_on_both_sides(self):
        self.release['data_version'] = self.health['data_version'] = None
        with patch.object(self.smoke, 'read_json', self.fake_read), patch.object(self.smoke, 'request', self.fake_request):
            result = self.smoke.check('http://local.test', self.release, feedback=False, seed_ids=['a', 'b'])
        self.assertTrue(result['passed'])
        self.health.pop('data_version')
        with patch.object(self.smoke, 'read_json', self.fake_read), patch.object(self.smoke, 'request') as request:
            with self.assertRaisesRegex(RuntimeError, 'data_version'):
                self.smoke.check('http://local.test', self.release, feedback=False)
        request.assert_not_called()
