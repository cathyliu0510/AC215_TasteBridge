import importlib.util
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.request import Request


def load(name, filename):
    path = Path(__file__).resolve().parents[2] / 'deploy/cloud-run' / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicationAccess(unittest.TestCase):
    def setUp(self):
        self.deploy = load('publication_access', 'deploy.py')
        self.directory = tempfile.TemporaryDirectory()
        self.state = Path(self.directory.name)
        self.deploy.STATE = self.state
        self.release = dict(tag='test-release', model_version='b2-als-gr-test', source_trees={'backend': 'tree'},
                            images={'frontend': 'local-front', 'backend': 'local-back', 'backend-base': 'local-base'},
                            image_ids={'frontend': 'id-front', 'backend': 'id-back', 'backend-base': 'id-base'})
        (self.state / 'release.json').write_text(json.dumps(self.release))
        (self.state / 'local-smoke.json').write_text(json.dumps(dict(tag='test-release', passed=True,
                                                               image_ids=self.release['image_ids'])))
        self.calls = []
        self.url = 'https://tastebridge-staging-test.us-central1.run.app'

    def tearDown(self):
        self.directory.cleanup()

    def command(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if args[:4] == ('gcloud', 'run', 'services', 'list'):
            return '[]'
        if args[:4] == ('gcloud', 'run', 'services', 'describe'):
            if getattr(self, 'fail_describe', False):
                raise subprocess.CalledProcessError(1, args)
            return json.dumps({'status': {'url': self.url, 'latestReadyRevisionName': 'test-revision'}})
        if args[:3] == ('gcloud', 'auth', 'print-identity-token'):
            return 'dummy-test-identity-token'
        if args[:3] == ('docker', 'context', 'inspect'):
            return 'unix:///test/socket'
        if any(str(argument).endswith('smoke.py') for argument in args) and getattr(self, 'fail_smoke', False):
            raise subprocess.CalledProcessError(1, args)
        return ''

    def image(self, image, expression):
        if expression == '{{.Id}}':
            return dict(zip(self.release['images'].values(), self.release['image_ids'].values()))[image]
        return json.dumps([image.rsplit(':', 1)[0] + '@sha256:test'])

    def publish(self, **kwargs):
        with patch.object(self.deploy, 'run', side_effect=self.command), \
                patch.object(self.deploy, 'inspect', side_effect=self.image), \
                patch.object(self.deploy, 'source_trees', return_value=self.release['source_trees']), \
                patch.object(self.deploy.shutil, 'which', return_value='gcloud'):
            with redirect_stdout(io.StringIO()):
                self.deploy.publish(**kwargs)

    def test_publication_preserves_iam_and_records_verified_deployment(self):
        self.publish()
        commands = ' '.join(str(argument) for args, _ in self.calls for argument in args)
        for forbidden in ('add-iam-policy-binding', 'set-iam-policy', 'allUsers', 'allow-unauthenticated'):
            self.assertNotIn(forbidden, commands)
        record = json.loads((self.state / 'deployment.json').read_text())
        self.assertEqual(record['status'], 'deployed_and_api_verified')
        self.assertEqual(record['access_policy'], 'preserved')

    def test_existing_ingress_and_authentication_settings_are_preserved(self):
        current = {'metadata': {'annotations': {'run.googleapis.com/ingress': 'internal',
                    'run.googleapis.com/invoker-iam-disabled': 'false',
                    'run.googleapis.com/default-url-disabled': 'true'}}}
        service = self.deploy.service_spec({'frontend': 'front', 'backend': 'back'}, current)
        for key, value in current['metadata']['annotations'].items():
            self.assertEqual(service['metadata']['annotations'][key], value)

    def test_authorized_token_uses_stdin_and_is_absent_from_argv_and_files(self):
        self.publish(authenticated=True)
        verification = next((args, kwargs) for args, kwargs in self.calls if '--identity-token-stdin' in args)
        self.assertEqual(verification[1]['input'], 'dummy-test-identity-token\n')
        self.assertNotIn('dummy-test-identity-token', str(verification[0]))
        for file in self.state.iterdir():
            self.assertNotIn('dummy-test-identity-token', file.read_text())

    def test_failed_verification_keeps_the_actual_deployment_outcome(self):
        self.fail_smoke = True
        with self.assertRaisesRegex(SystemExit, 'Service updated, but verification failed'):
            self.publish()
        self.assertEqual(json.loads((self.state / 'deployment.json').read_text())['status'], 'deployed_unverified')
        self.assertEqual((self.state / 'url.txt').read_text().strip(), self.url)

    def test_failed_description_still_records_that_update_succeeded(self):
        self.fail_describe = True
        with self.assertRaisesRegex(SystemExit, 'Service update succeeded'):
            self.publish()
        self.assertEqual(json.loads((self.state / 'deployment.json').read_text())['status'], 'deployed_unverified')

    def test_absent_or_unexpected_default_url_never_loses_the_update_record(self):
        for url in (None, 'https://unrelated.example.com'):
            self.url = url
            with self.assertRaisesRegex(SystemExit, 'origin is unexpected'):
                self.publish()
            self.assertEqual(json.loads((self.state / 'deployment.json').read_text())['status'], 'deployed_unverified')
            self.assertFalse((self.state / 'url.txt').exists())

    def test_demo_model_requires_explicit_permission_before_any_upload(self):
        for identity in ('b2-als-synthetic-example', 'sample-shelf-toy-v1'):
            release = {**self.release, 'model_version': identity}
            with self.assertRaisesRegex(SystemExit, 'Demo model detected'):
                self.deploy.publication_model_kind(release)
            self.assertEqual(self.deploy.publication_model_kind(release, True), 'demo_model')
        self.assertIn('not_independently_verified', self.deploy.publication_model_kind(self.release))
        (self.state / 'release.json').write_text(json.dumps({**self.release, 'model_version': 'b2-als-synthetic-test'}))
        with patch.object(self.deploy, 'run') as command:
            with self.assertRaisesRegex(SystemExit, 'Demo model detected'):
                self.deploy.publish()
            command.assert_not_called()


class IdentityScope(unittest.TestCase):
    def setUp(self):
        self.smoke = load('identity_scope', 'smoke.py')

    def test_invalid_origin_or_token_is_rejected(self):
        for url in ('http://example.com', 'https://user@example.com', 'https://example.com/path', 'https://example.com?q=x'):
            with self.assertRaises(ValueError):
                self.smoke.configure_identity_token(url, 'dummy-token')
        for token in ('', 'two tokens', 'a\nb', 'x' * 16385):
            with self.assertRaises(ValueError):
                self.smoke.configure_identity_token('https://example.com', token)

    def test_token_is_sent_only_to_the_explicit_https_origin(self):
        self.smoke.configure_identity_token('https://example.com', 'dummy-token')
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = 'https://example.com/api/health'
        response.read.return_value = b'{}'
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(self.smoke.urllib.request, 'build_opener', return_value=opener):
            self.smoke.request('https://example.com', '/api/health')
            request = opener.open.call_args.args[0]
            self.assertEqual(request.get_header('Authorization'), 'Bearer dummy-token')
            with self.assertRaisesRegex(ValueError, 'restricted'):
                self.smoke.request('https://other.example.com', '/api/health')

    def test_cross_origin_redirect_cannot_receive_the_token(self):
        self.smoke.configure_identity_token('https://example.com', 'dummy-token')
        handler = self.smoke.SameOriginRedirect()
        request = Request('https://example.com', headers={'Authorization': 'Bearer dummy-token'})
        for target in ('https://other.example.com/a', 'http://example.com/a'):
            with self.assertRaisesRegex(ValueError, 'Cross-origin'):
                handler.redirect_request(request, None, 302, 'Found', {}, target)


if __name__ == '__main__':
    unittest.main()
