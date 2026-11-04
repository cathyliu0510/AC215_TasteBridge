import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from tools.check_ms3 import REQUIRED, check


class EvidenceChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "evidence.txt").write_text("test fixture, not real submission evidence")
        self.manifest = {"requirements": [
            {"id": key, "status": "verified", "evidence": ["evidence.txt"]}
            for key in sorted(REQUIRED)
        ]}

    def tearDown(self):
        self.temp.cleanup()

    def test_local_or_historical_results_cannot_complete_the_manifest(self):
        for status in ("pending", "local_only", "historical_only"):
            manifest = copy.deepcopy(self.manifest)
            manifest["requirements"][0]["status"] = status
            self.assertFalse(check(manifest, self.root)["recorded_evidence_complete"])
        self.assertTrue(check(self.manifest, self.root)["recorded_evidence_complete"])

    def test_verified_without_a_file_or_missing_requirements_cannot_pass(self):
        self.manifest["requirements"][0]["evidence"] = []
        self.assertFalse(check(self.manifest, self.root)["recorded_evidence_complete"])
        self.manifest["requirements"].pop()
        self.assertTrue(check(self.manifest, self.root)["errors"])

    def test_evidence_cannot_escape_the_repository(self):
        for name in ("../outside.json", str(self.root / "evidence.txt")):
            self.manifest["requirements"][0]["evidence"] = [name]
            self.assertIn("inside the repository", check(self.manifest, self.root)["errors"][0])


class DeploymentConfiguration(unittest.TestCase):
    def test_current_frontend_host_contract_and_internal_api_are_explicit(self):
        source = Path(__file__).resolve().parents[2] / "deploy/cloud-run/deploy.py"
        spec = importlib.util.spec_from_file_location("cloud_run_preparation", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        service = module.service_spec({"frontend": "frontend@sha256:test", "backend": "backend@sha256:test"})
        containers = service["spec"]["template"]["spec"]["containers"]
        frontend, backend = containers
        env = {item["name"]: item["value"] for item in frontend["env"]}
        self.assertEqual(env["TASTEBRIDGE_HOST"], "0.0.0.0")
        self.assertEqual(env["API_BASE_URL"], "http://127.0.0.1:9000")
        self.assertEqual(frontend["ports"], [{"containerPort": 8080}])
        self.assertNotIn("ports", backend)


if __name__ == "__main__":
    unittest.main()
