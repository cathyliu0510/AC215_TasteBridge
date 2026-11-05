import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.audit_serving_identity import audit, compare_container, fingerprint, FILES


def matrix(path, rows, columns, value=0.5):
    header = repr({'descr': '<f4', 'fortran_order': False, 'shape': (rows, columns)}).encode()
    header += b' ' * ((64 - ((10 + len(header) + 1) % 64)) % 64) + b'\n'
    path.write_bytes(b'\x93NUMPY\x01\x00' + struct.pack('<H', len(header)) + header + struct.pack('<f', value) * rows * columns)


class IdentityAudit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'books.json').write_text(json.dumps([{'book_id':str(i),'title':'Book','author':'Author'} for i in range(15)]))
        (self.root / 'meta.json').write_text(json.dumps({'model_version':'same-name','data_version':'data','counts':{'books':15},'hyperparameters':{'factors':3}}))
        matrix(self.root / 'item_embeddings.npy', 15, 3)
        matrix(self.root / 'coords_2d.npy', 15, 2)
        self.lock = {'schema_version':1,'model_version':'same-name','data_version':'data','num_books':15,
                     'files':{name:fingerprint(self.root / name) for name in FILES}}

    def tearDown(self):
        self.temp.cleanup()

    def test_reviewed_export_audit_preserves_input_and_records_no_execution(self):
        before = {name:(self.root/name).read_bytes() for name in FILES}
        result = audit(self.root, self.lock)
        self.assertEqual(result['matrices']['item_embeddings.npy']['shape'], [15,3])
        self.assertFalse(result['training_executed'])
        self.assertFalse(result['cloud_deployment_verified'])
        self.assertEqual(before,{name:(self.root/name).read_bytes() for name in FILES})

    def test_same_model_name_does_not_hide_changed_weights(self):
        matrix(self.root / 'item_embeddings.npy',15,3,value=0.75)
        with self.assertRaisesRegex(ValueError,'bytes differ.*item_embeddings'):
            audit(self.root,self.lock)

    def test_stale_container_and_stale_frontend_are_independently_detected(self):
        hashes={name:record['sha256'] for name,record in self.lock['files'].items()}
        previous={'artifact_sha256':dict(hashes),'source_trees':{'frontend/prototype':'old','src/backend':'api'}}
        result=compare_container(previous,hashes,{'frontend/prototype':'new','src/backend':'api'})
        self.assertTrue(result['same_artifact_bytes'])
        self.assertFalse(result['identity_compatible_with_current_export_and_app'])
        previous['artifact_sha256']['coords_2d.npy']='0'*64
        result=compare_container(previous,hashes,previous['source_trees'])
        self.assertTrue(result['same_app_sources'])
        self.assertEqual(result['different_files'],['coords_2d.npy'])
        self.assertFalse(result['identity_compatible_with_current_export_and_app'])

    def test_missing_source_identity_and_modified_dvc_index_cannot_verify_lineage(self):
        import hashlib
        hashes={name:record['sha256'] for name,record in self.lock['files'].items()}
        result=compare_container({'artifact_sha256':hashes},hashes,{})
        self.assertFalse(result['identity_compatible_with_current_export_and_app'])
        index=self.root/'index.json'
        index.write_text(json.dumps([{'relpath':'current/'+name,'md5':record['md5']} for name,record in self.lock['files'].items()]))
        self.lock['source_dvc_directory_md5']=hashlib.md5(index.read_bytes()).hexdigest()
        self.assertTrue(audit(self.root,self.lock,index)['dvc_index_verified'])
        index.write_text(index.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'pinned lock'):
            audit(self.root,self.lock,index)

    def test_even_a_locked_nonfinite_or_wrong_dimension_matrix_is_rejected(self):
        matrix(self.root/'item_embeddings.npy',15,3,float('nan'))
        self.lock['files']['item_embeddings.npy']=fingerprint(self.root/'item_embeddings.npy')
        with self.assertRaisesRegex(ValueError,'nonfinite'):
            audit(self.root,self.lock)
        matrix(self.root/'item_embeddings.npy',15,2)
        self.lock['files']['item_embeddings.npy']=fingerprint(self.root/'item_embeddings.npy')
        with self.assertRaisesRegex(ValueError,'shape'):
            audit(self.root,self.lock)

    def test_symlink_or_incomplete_lock_fails(self):
        bad=copy.deepcopy(self.lock);del bad['files']['meta.json']
        with self.assertRaisesRegex(ValueError,'exactly the four'):
            audit(self.root,bad)
        (self.root/'coords_2d.npy').unlink();(self.root/'coords_2d.npy').symlink_to(self.root/'item_embeddings.npy')
        with self.assertRaisesRegex(ValueError,'regular artifact'):
            audit(self.root,self.lock)

    def test_build_refuses_stale_model_lock_before_any_docker_command(self):
        module_path=Path(__file__).resolve().parents[2]/'deploy/cloud-run/deploy.py'
        spec=importlib.util.spec_from_file_location('locked_build',module_path)
        deploy=importlib.util.module_from_spec(spec);spec.loader.exec_module(deploy)
        lock_path=self.root/'reviewed-lock.json';lock_path.write_text(json.dumps(self.lock))
        deploy.HERE=self.root;deploy.STATE=self.root/'.state'
        stage=self.root/'.artifacts';stage.mkdir()
        for name in FILES:(stage/name).write_bytes((self.root/name).read_bytes())
        matrix(stage/'item_embeddings.npy',15,3,value=0.75)
        with patch.object(deploy,'run',return_value='') as run:
            with self.assertRaisesRegex(SystemExit,'No images were built'):
                deploy.build(self.root,artifact_lock=lock_path)
        self.assertFalse(any(call.args[0]=='docker' for call in run.call_args_list))


if __name__ == '__main__':
    unittest.main()
