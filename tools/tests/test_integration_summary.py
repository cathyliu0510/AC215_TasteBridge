import json
from pathlib import Path
import tempfile
import unittest

from tools.evidence_contracts import EXPORTS, file_sha256
from tools.summarize_integration import compare, normalized_document, valid_api_examples


class ReproductionEvidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.a, self.b = (Path(self.temp.name) / name for name in ('a', 'b'))
        for folder in (self.a, self.b):
            folder.mkdir()
            for name in ('raw/a.gz', 'processed/books.parquet', 'processed/interactions.parquet',
                         'artifacts/current/item_embeddings.npy', 'artifacts/current/coords_2d.npy',
                         'evaluation/held-out/summary.csv'):
                path = folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'same fixture bytes')
            self.write(folder, 'raw/manifest.json', {'created_at': 'different-' + folder.name, 'source': 'synthetic'})
            self.write(folder, 'processed/manifest.json', {'created_at': folder.name, 'data_version': 'synthetic-example',
                'inputs': {'created_at': folder.name, 'mode': 'synthetic'}, 'params': {'seed': 42}})
            self.write(folder, 'artifacts/current/books.json', [{'book_id': 'one', 'title': 'Invented One'}])
            self.write(folder, 'artifacts/current/meta.json', {'model_version': 'synthetic-model',
                'data_version': 'synthetic-example', 'created_at': folder.name, 'seconds': len(folder.name),
                'hyperparameters': {'seed': 42, 'factors': 16}, 'map_method': 'umap'})
            self.write(folder, 'evaluation/held-out/config.json', {'seconds': len(folder.name),
                'arguments': {'interactions': str(folder / 'processed/interactions.parquet'),
                              'books': str(folder / 'processed/books.parquet'), 'out': str(folder / 'evaluation'),
                              'seed': 42, 'n_pairs': 20}})
            examples = {'input_kind': 'synthetic', 'examples': []}
            for mode in ('least_misery', 'average'):
                examples['examples'].append({'request': {'aggregation': mode, 'k': 5,
                    'reader_a': [f'a{i}' for i in range(5)], 'reader_b': [f'b{i}' for i in range(5)]},
                    'response': {'model_version': 'synthetic-model', 'aggregation': mode,
                        'recommendations': [{'book': {'book_id': f'bridge{i}'}, 'score': .5, 'fit_a': .5, 'fit_b': .5,
                            'reasons': {reader: {'seed_id': reader + '0', 'text': 'Invented reason'}
                                        for reader in ('reader_a', 'reader_b')}} for i in range(5)]}})
            self.write(folder, 'api-examples.json', examples)
            self.write(folder, 'run.json', {'status': 'passed', 'input_kind': 'synthetic',
                'source_commit': 'same', 'source_sha256': {'source.py': 'same'}, 'source_dirty': False,
                'data_version': 'synthetic-example', 'model_version': 'synthetic-model',
                'parameters': {'seed': 42, 'factors': 16}, 'frontend_sha256': 'same'})
            self.refresh_recorded_hashes(folder)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def write(folder, name, value):
        (folder / name).write_text(json.dumps(value))

    def mutate(self, folder, name, change, *, refresh=False):
        value = json.loads((folder / name).read_text())
        change(value)
        self.write(folder, name, value)
        if refresh:
            self.refresh_recorded_hashes(folder)

    def refresh_recorded_hashes(self, folder):
        record = json.loads((folder / 'run.json').read_text())
        record['export_sha256'] = {name: file_sha256(folder / 'artifacts/current' / name) for name in EXPORTS}
        record['processed_sha256'] = {name: file_sha256(folder / 'processed' / name)
                                     for name in ('books.parquet', 'interactions.parquet', 'manifest.json')}
        self.write(folder, 'run.json', record)

    def test_identical_content_with_explicit_timestamp_duration_and_run_path_variations_passes(self):
        self.assertTrue(compare(self.a, self.b)['passed'])
        self.mutate(self.b, 'artifacts/current/meta.json', lambda value: value.update(seconds=99), refresh=True)
        self.assertTrue(compare(self.a, self.b)['passed'])

    def test_successful_runs_with_changed_vectors_fail_reproduction(self):
        self.assertTrue(compare(self.a, self.b)['passed'])
        (self.b / 'artifacts/current/item_embeddings.npy').write_bytes(b'different vectors')
        result = compare(self.a, self.b)
        self.assertFalse(result['passed'])
        self.assertFalse(result['checks']['all_compared_content_hashes_match'])
        self.assertFalse(result['checks']['all_recorded_export_hashes_match_bytes'])

    def test_changed_catalogue_fails_even_after_updating_its_declared_hash(self):
        self.mutate(self.b, 'artifacts/current/books.json', lambda value: value[0].update(title='Changed'), refresh=True)
        result = compare(self.a, self.b)
        self.assertFalse(result['passed'])
        self.assertTrue(result['checks']['all_recorded_export_hashes_match_bytes'])

    def test_changed_export_metadata_configuration_and_parameters_cannot_hide_behind_same_vectors(self):
        cases = [('artifacts/current/meta.json', lambda value: value['hyperparameters'].update(factors=32)),
                 ('artifacts/current/meta.json', lambda value: value.update(map_method='pca')),
                 ('evaluation/held-out/config.json', lambda value: value['arguments'].update(seed=9)),
                 ('processed/manifest.json', lambda value: value['params'].update(seed=9)),
                 ('run.json', lambda value: value['parameters'].update(seed=9))]
        for name, change in cases:
            with self.subTest(name=name):
                original = (self.b / name).read_text()
                self.mutate(self.b, name, change, refresh=True)
                self.assertFalse(compare(self.a, self.b)['passed'])
                (self.b / name).write_text(original)
                self.refresh_recorded_hashes(self.b)

    def test_extra_raw_files_in_either_run_are_not_ignored(self):
        for folder in (self.a, self.b):
            with self.subTest(folder=folder.name):
                extra = folder / 'raw/extra.gz'
                extra.write_bytes(b'extra input')
                result = compare(self.a, self.b)
                self.assertFalse(result['passed'])
                self.assertFalse(result['checks']['same_raw_file_set'])
                extra.unlink()

    def test_empty_api_examples_do_not_prove_reproduction(self):
        for empty in ({'input_kind': 'synthetic', 'examples': []}, {}, {'examples': []}):
            with self.subTest(empty=empty):
                for folder in (self.a, self.b):
                    self.write(folder, 'api-examples.json', empty)
                result = compare(self.a, self.b)
                self.assertFalse(result['passed'])
                self.assertFalse(result['checks']['nonempty_full_shelf_api_examples'])

    def test_same_rankings_with_changed_request_score_or_reason_fail(self):
        changes = [lambda value: value['examples'][0]['request']['reader_a'].__setitem__(0, 'different'),
                   lambda value: value['examples'][0]['response']['recommendations'][0].update(score=.6),
                   lambda value: value['examples'][0]['response']['recommendations'][0]['reasons']['reader_a'].update(text='Changed'),
                   lambda value: value['examples'][0]['request'].update(created_at='semantically retained')]
        original = (self.b / 'api-examples.json').read_text()
        for change in changes:
            with self.subTest(change=change):
                self.mutate(self.b, 'api-examples.json', change)
                result = compare(self.a, self.b)
                self.assertTrue(result['checks']['same_full_shelf_api_rankings'])
                self.assertFalse(result['checks']['same_full_shelf_api_requests_and_responses'])
                self.assertFalse(result['passed'])
                (self.b / 'api-examples.json').write_text(original)

    def test_missing_required_files_and_symlinked_inputs_fail_closed(self):
        path = self.b / 'artifacts/current/books.json'
        path.unlink()
        self.assertFalse(compare(self.a, self.b)['passed'])
        path.symlink_to(self.a / 'artifacts/current/books.json')
        self.assertFalse(compare(self.a, self.b)['passed'])

    def test_timestamp_named_configuration_parameter_is_not_discarded(self):
        self.mutate(self.b, 'evaluation/held-out/config.json',
                    lambda value: value['arguments'].update(seconds=99, created_at='important setting'))
        self.assertFalse(compare(self.a, self.b)['passed'])

    def test_failed_or_operator_data_cannot_enter_the_synthetic_evidence_package(self):
        for key, value in (('status', 'failed'), ('input_kind', 'operator_supplied')):
            path = self.b / 'run.json'
            original = json.loads(path.read_text())
            self.write(self.b, 'run.json', {**original, key: value})
            with self.assertRaisesRegex(ValueError, 'successful, explicitly synthetic'):
                compare(self.a, self.b)
            self.write(self.b, 'run.json', original)


class HistoricalSnapshotCompatibility(unittest.TestCase):
    def test_existing_saved_two_run_metadata_and_complete_api_examples_still_agree(self):
        base = Path(__file__).resolve().parents[2] / 'docs/ms3/evidence/local-integration-20261104/runs'
        names = {'processed-manifest.json': 'processed/manifest.json', 'export-meta.json': 'artifacts/current/meta.json',
                 'evaluation-config.json': 'evaluation/held-out/config.json'}
        for saved, original in names.items():
            with self.subTest(saved=saved):
                values = [json.loads((base / label / saved).read_text()) for label in ('run-a', 'run-b')]
                self.assertEqual(normalized_document(original, values[0], base / 'run-a'),
                                 normalized_document(original, values[1], base / 'run-b'))
        examples = [json.loads((base / label / 'api-examples.json').read_text()) for label in ('run-a', 'run-b')]
        self.assertTrue(all(valid_api_examples(value) for value in examples))
        self.assertEqual(examples[0], examples[1])
