import json
from pathlib import Path
import tempfile
import unittest

from tools.bind_serving_evidence import main
from tools.evidence_contracts import (EXPORTS, SOURCE_REQUIRED, bind_serving_evidence, canonical_sha256,
    capture_serving_sources, file_sha256, read_json, validate_source_manifest, verify_evidence_binding)


class ServingEvidenceContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'checkout'
        self.root.mkdir()
        for name in SOURCE_REQUIRED:
            self.write_bytes(self.root / name, ('fixture ' + name).encode())
        for name in ('src/backend/app/routers/books.py', 'frontend/prototype/src/a/app.mjs',
                     'frontend/prototype/src/a/shared/fonts/font.woff2', 'frontend/prototype/package-lock.json'):
            self.write_bytes(self.root / name, b'fixture')
        self.bundle = Path(self.temp.name) / 'bundle'
        self.bundle.mkdir()
        self.model = Path(self.temp.name) / 'model'
        self.model.mkdir()
        for name in EXPORTS:
            self.write_bytes(self.model / name, b'fixture bytes')
        self.write_json(self.model / 'meta.json', {'model_version': 'real-test', 'data_version': 'gr-test'})
        source = capture_serving_sources(self.root)
        self.write_json(self.bundle / 'source-manifest.json', source)
        self.run = self.bundle / 'run.json'
        self.write_json(self.run, {'status': 'verified', 'services_stopped': True, 'source_manifest_sha256': source['sha256'],
            'source_sha256': source['files'], 'source_commit': 'recorded-commit', 'source_dirty': True,
            'artifact_sha256': {name: file_sha256(self.model / name) for name in EXPORTS},
            'model_version': 'real-test', 'data_version': 'gr-test', 'books': 15})
        self.write_json(self.bundle / 'api-check.json', {'passed': True,
            'health': {'model_version': 'real-test', 'data_version': 'gr-test', 'num_books': 15}})
        for name in ('frontend-build.log', 'backend.log', 'frontend.log', 'test-output.txt', 'desktop.png'):
            self.write_bytes(self.bundle / name, ('invented test fixture ' + name).encode())

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def write_bytes(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    @staticmethod
    def write_json(path, value):
        path.write_text(json.dumps(value))

    def binding(self, evidence=()):
        return bind_serving_evidence(self.run, self.model, evidence, source_root=self.root)

    def test_recursive_routes_relay_locks_assets_and_generated_pages_are_in_canonical_source_digest(self):
        source = capture_serving_sources(self.root)
        self.assertEqual(source['sha256'], validate_source_manifest(source))
        for name in ('src/backend/app/routers/books.py', 'frontend/prototype/scripts/serve.mjs',
                     'src/backend/uv.lock', 'frontend/prototype/package-lock.json',
                     'frontend/prototype/src/a/shared/fonts/font.woff2', 'frontend/prototype/dist/b/index.html'):
            with self.subTest(name=name):
                self.assertIn(name, source['files'])
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(b'changed')
                self.assertNotEqual(source['sha256'], capture_serving_sources(self.root)['sha256'])
                path.write_bytes(original)
        self.write_bytes(self.root / 'private/reader-history.json', b'private fixture; outside source scope')
        self.assertEqual(source, capture_serving_sources(self.root))

    def test_source_manifest_rejects_symlinked_files_and_nested_source_directories(self):
        target = self.root / 'src/backend/app/routers/books.py'
        target.unlink()
        target.symlink_to(self.root / 'src/backend/app/main.py')
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            capture_serving_sources(self.root)
        target.unlink()
        target.parent.rmdir()
        target.parent.symlink_to(self.root / 'frontend', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            capture_serving_sources(self.root)

    def test_binding_hashes_all_model_files_and_supplied_evidence_without_claiming_test_or_browser_execution(self):
        binding = self.binding([('screenshot', Path('desktop.png')), ('test', Path('test-output.txt'))])
        self.assertEqual(set(binding['artifact_sha256']), set(EXPORTS))
        self.assertFalse(binding['browser_actions_verified'])
        self.assertFalse(binding['test_execution_verified'])
        self.assertEqual(len(binding['evidence']), 8)
        serialized = json.dumps(binding)
        self.assertNotIn('invented test fixture', serialized)
        self.assertNotIn(str(self.model), serialized)
        verify_evidence_binding(binding, self.bundle)
        (self.bundle / 'desktop.png').write_bytes(b'replaced screenshot')
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            verify_evidence_binding(binding, self.bundle)

    def test_changed_sources_or_any_of_the_four_model_artifacts_cannot_be_bound_to_old_run(self):
        path = self.root / 'src/backend/app/routers/books.py'
        path.write_bytes(b'changed route')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.binding()
        path.write_bytes(b'fixture')
        for name in EXPORTS:
            with self.subTest(name=name):
                path = self.model / name
                original = path.read_bytes()
                path.write_bytes(b'changed model')
                with self.assertRaisesRegex(ValueError, 'all four'):
                    self.binding()
                path.write_bytes(original)

    def test_source_digest_and_legacy_partial_capture_fail_closed(self):
        source = read_json(self.bundle / 'source-manifest.json')
        source['files']['src/backend/app/main.py'] = '0' * 64
        self.write_json(self.bundle / 'source-manifest.json', source)
        with self.assertRaisesRegex(ValueError, 'digest'):
            self.binding()
        self.write_json(self.bundle / 'source-manifest.json', capture_serving_sources(self.root))
        record = read_json(self.run)
        record.pop('source_manifest_sha256')
        self.write_json(self.run, record)
        with self.assertRaisesRegex(ValueError, 'rerun verification'):
            self.binding()

    def test_api_identity_and_passing_status_are_checked(self):
        for patch in ({'passed': False}, {'health': {'model_version': 'another-model', 'data_version': 'gr-test', 'num_books': 15}}):
            original = read_json(self.bundle / 'api-check.json')
            self.write_json(self.bundle / 'api-check.json', {**original, **patch})
            with self.assertRaisesRegex(ValueError, 'API record'):
                self.binding()
            self.write_json(self.bundle / 'api-check.json', original)

    def test_live_run_logs_are_not_bound_as_final_evidence(self):
        record = read_json(self.run)
        self.write_json(self.run, {**record, 'services_stopped': False})
        with self.assertRaisesRegex(ValueError, 'Stop this run'):
            self.binding()

    def test_evidence_cannot_traverse_escape_or_follow_a_symlink(self):
        for path in (Path('../model/meta.json'), self.model / 'meta.json'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'inside'):
                self.binding([('report', path)])
        (self.bundle / 'linked.log').symlink_to(self.model / 'meta.json')
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            self.binding([('log', Path('linked.log'))])

    def test_verifier_rejects_a_self_consistent_digest_with_missing_model_identity(self):
        binding = self.binding()
        binding['artifact_sha256'].pop('books.json')
        binding['sha256'] = canonical_sha256({key: value for key, value in binding.items() if key != 'sha256'})
        with self.assertRaisesRegex(ValueError, 'all four'):
            verify_evidence_binding(binding, self.bundle)

    def test_cli_never_overwrites_an_existing_binding(self):
        existing = self.bundle / 'binding.json'
        existing.write_bytes(b'preserve this evidence')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            main(['bind', '--run', str(self.run), '--artifact-dir', str(self.model), '--source-root', str(self.root),
                  '--out', str(existing)])
        self.assertEqual(existing.read_bytes(), b'preserve this evidence')
