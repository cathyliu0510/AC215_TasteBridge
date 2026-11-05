import json
from pathlib import Path
import tempfile
import unittest

from tools.verify_serving_export import input_kind, inspect_export, EXPORTS


class ExistingExport(unittest.TestCase):
    def test_synthetic_and_fixture_identity_never_become_real_data_evidence(self):
        self.assertEqual(input_kind({'model_version': 'b2-als-synthetic-123'}), 'trained_synthetic')
        self.assertEqual(input_kind({'model_version': 'sample-shelf-toy-v1'}), 'fixed_fixture')
        self.assertEqual(input_kind({'model_version': 'b2-als-gr-123'}), 'operator_supplied_unverified_provenance')

    def test_regular_files_and_enough_books_are_required_without_modifying_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in EXPORTS:
                (root / name).write_text('{}')
            (root / 'meta.json').write_text(json.dumps({'model_version': 'b2-als-synthetic-test'}))
            (root / 'books.json').write_text(json.dumps([{'book_id': str(i)} for i in range(15)]))
            before = {name: (root / name).read_bytes() for name in EXPORTS}
            _, meta, books = inspect_export(root)
            self.assertEqual(len(books), 15)
            self.assertEqual(meta['model_version'], 'b2-als-synthetic-test')
            self.assertEqual(before, {name: (root / name).read_bytes() for name in EXPORTS})
            (root / 'coords_2d.npy').unlink()
            (root / 'coords_2d.npy').symlink_to(root / 'item_embeddings.npy')
            with self.assertRaisesRegex(ValueError, 'regular model export'):
                inspect_export(root)

    def test_missing_identity_and_incomplete_catalogues_fail_before_services_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in EXPORTS:
                (root / name).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'model_version'):
                inspect_export(root)
            (root / 'meta.json').write_text(json.dumps({'model_version': 'test'}))
            (root / 'books.json').write_text('[]')
            with self.assertRaisesRegex(ValueError, 'At least 15'):
                inspect_export(root)


if __name__ == '__main__':
    unittest.main()
