import json
from pathlib import Path
import tempfile
import unittest

from tools.summarize_integration import compare


class ReproductionEvidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.a, self.b = (Path(self.temp.name) / name for name in ("a", "b"))
        for folder in (self.a, self.b):
            folder.mkdir()
            (folder / "run.json").write_text(json.dumps({"status": "passed", "input_kind": "synthetic",
                "source_commit": "same", "source_sha256": {"source.py": "same"}, "source_dirty": False,
                "data_version": "synthetic-example"}))
            for name in ("raw/a.gz", "processed/books.parquet", "processed/interactions.parquet",
                         "artifacts/current/item_embeddings.npy", "artifacts/current/coords_2d.npy",
                         "evaluation/held-out/summary.csv"):
                path = folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"same fixture bytes")
            (folder / "api-examples.json").write_text(json.dumps({"examples": [{"request": {"aggregation": "average"},
                "response": {"recommendations": [{"book": {"book_id": "one"}}]}}]}))

    def tearDown(self):
        self.temp.cleanup()

    def test_successful_runs_with_changed_vectors_fail_reproduction(self):
        self.assertTrue(compare(self.a, self.b)["passed"])
        (self.b / "artifacts/current/item_embeddings.npy").write_bytes(b"different vectors")
        result = compare(self.a, self.b)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["all_compared_content_hashes_match"])

    def test_failed_or_operator_data_cannot_enter_the_synthetic_evidence_package(self):
        for key, value in (("status", "failed"), ("input_kind", "operator_supplied")):
            path = self.b / "run.json"
            original = json.loads(path.read_text())
            changed = {**original, key: value}
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "successful, explicitly synthetic"):
                compare(self.a, self.b)
            path.write_text(json.dumps(original))
