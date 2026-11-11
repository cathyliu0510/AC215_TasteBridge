#!/usr/bin/env python3
"""Exercise the packaged app locally or an explicitly supplied public URL."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = Path(__file__).resolve().parent
STATE = HERE / '.state'
_identity = None
ARTIFACT_FILES = ('books.json', 'item_embeddings.npy', 'coords_2d.npy', 'meta.json')


def origin(url):
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)


def configure_identity_token(base, token):
    """Keep an operator-supplied ID token in memory and bind it to one HTTPS origin."""
    global _identity
    _identity = None
    parsed = urllib.parse.urlsplit(base)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('Authenticated verification requires a credential-free HTTPS service origin')
    token = token.strip()
    if not token or len(token) > 16384 or any(character.isspace() for character in token):
        raise ValueError('Provide one nonempty identity token through stdin')
    _identity = (origin(base), token)


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _identity is not None and origin(newurl) != _identity[0]:
            raise ValueError('Cross-origin redirect refused during authenticated verification')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request(base, path, data=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(base + path, data=body,
                                 headers={'Content-Type': 'application/json'} if body else {})
    if _identity is not None:
        if origin(req.full_url) != _identity[0]:
            raise ValueError('Identity token is restricted to its configured service origin')
        req.add_header('Authorization', 'Bearer ' + _identity[1])
        open_request = urllib.request.build_opener(SameOriginRedirect()).open
    else:
        open_request = urllib.request.urlopen
    with open_request(req, timeout=60) as response:
        return response.geturl(), response.read()


def read_json(base, path, data=None):
    return json.loads(request(base, path, data)[1])


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def release_identity(release):
    """Derive serving identity from the reviewed export/build, never the live API."""
    hashes = release.get('artifact_sha256')
    require(isinstance(hashes, dict) and set(hashes) == set(ARTIFACT_FILES) and
            all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
                for value in hashes.values()),
            'Release needs SHA256 hashes for exactly the four artifact files; rebuild or supply the reviewed export identity')
    require('data_version' in release and
            (release['data_version'] is None or
             (isinstance(release['data_version'], str) and bool(release['data_version']))),
            'Release needs an explicit data_version (null is allowed when unrecorded)')
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode('utf-8')).hexdigest()
    return fingerprint, release['data_version']


def check(base, release, feedback, seed_ids=None):
    fingerprint, data_version = release_identity(release)
    health = read_json(base, '/api/health')
    require(health['status'] == 'ok' and health['num_books'] == release['num_books']
            and health['model_version'] == release['model_version'], f'Wrong model: {health}')
    require(health.get('artifact_fingerprint') == fingerprint, 'Wrong or missing artifact fingerprint in health')
    require('data_version' in health and health['data_version'] == data_version,
            'Wrong or missing data_version in health')
    final_url, html = request(base, '/')
    require(urllib.parse.urlparse(final_url).path == '/a/' and
            urllib.parse.parse_qs(urllib.parse.urlparse(final_url).query).get('api') == ['1'],
            f'Root did not enter the API-backed UI: {final_url}')
    require(b'TasteBridge' in html, 'Missing frontend HTML')
    frontend_health = read_json(base, '/frontend/health')
    require(frontend_health.get('status') == 'ok' and frontend_health.get('service') == 'frontend',
            'Frontend health failed')
    picks = []
    require(seed_ids is None or len(seed_ids) == 2, 'Supply exactly one book ID per reader')
    for index, query in enumerate(('The Hobbit', 'Gone Girl')):
        if seed_ids is None:
            matches = read_json(base, '/api/books/search?' + urllib.parse.urlencode({'q': query}))
            require(bool(matches), f'No matches for {query}')
            seed = matches[0]['book_id']
        else:
            seed = seed_ids[index]
        book = read_json(base, '/api/books/' + urllib.parse.quote(seed, safe=''))
        require(book['book_id'] == seed, 'Book detail ID mismatch')
        if seed_ids is not None:
            # The API accepts at most 100 characters, even when a catalogue title is longer.
            title_query = book['title'][:100]
            require(bool(read_json(base, '/api/books/search?' + urllib.parse.urlencode({'q': title_query}))),
                    'The selected catalogue title must be searchable')
        picks.append(book['book_id'])
    require(picks[0] != picks[1], 'Expected distinct reader selections')
    outputs = []
    for mode in ('least_misery', 'average'):
        result = read_json(base, '/api/recommend', dict(reader_a=picks[:1], reader_b=picks[1:], k=5, aggregation=mode))
        require(result['model_version'] == release['model_version'], 'Recommendation model mismatch')
        require(result.get('artifact_fingerprint') == fingerprint,
                'Recommendation artifact fingerprint mismatch or missing')
        require(result['aggregation'] == mode and len(result['recommendations']) == 5, 'Recommendation count/mode failed')
        require(len(result['galaxy']['bridges']) == 5, 'Missing map coordinates')
        ids = [item['book']['book_id'] for item in result['recommendations']]
        require(len(set(ids)) == 5 and not set(ids).intersection(picks), 'Recommendations duplicate or include favorites')
        bridge_positions = {point['book_id']: point for point in result['galaxy']['bridges']}
        require(set(bridge_positions) == set(ids), 'Map book IDs do not match recommendations')
        previous_score = math.inf
        for item in result['recommendations']:
            expected = min(item['fit_a'], item['fit_b']) if mode == 'least_misery' else (item['fit_a'] + item['fit_b']) / 2
            # SPEC responses independently round score and fits to four decimals.
            # Averaging the rounded fits can differ by up to 0.0001 from score.
            require(all(math.isfinite(item[key]) for key in ('score', 'fit_a', 'fit_b')) and
                    abs(item['score'] - expected) <= 1.00001e-4 and item['score'] <= previous_score + 1e-6,
                    'Recommendation score/ordering does not match the aggregation')
            previous_score = item['score']
            position = bridge_positions[item['book']['book_id']]
            require(all(math.isfinite(position[key]) and math.isfinite(item['position'][key]) and
                        abs(position[key] - item['position'][key]) < 1e-6 for key in ('x', 'y')),
                    'Map coordinates disagree with recommendation positions')
            require(item['reasons']['reader_a']['seed_id'] == picks[0] and
                    item['reasons']['reader_b']['seed_id'] == picks[1], 'Reasons assigned to wrong reader')
        outputs.append(dict(mode=mode, ids=[r['book']['book_id'] for r in result['recommendations']]))
    for path in ('/artifacts/current/meta.json', '/books.json', '/api/docs', '/.env'):
        try:
            request(base, path)
        except urllib.error.HTTPError as error:
            try:
                require(error.code == 404, f'Unexpected {error.code} at {path}')
            finally:
                error.close()
        else:
            raise RuntimeError(f'Private or unsupported route exposed: {path}')
    event = None
    if feedback:
        event = dict(book_id=outputs[0]['ids'][0], vote='would_read', model_version=release['model_version'])
        require(read_json(base, '/api/feedback', event)['ok'] is True, 'Feedback request failed')
    return dict(passed=True, tag=release['tag'], checked_at=datetime.now(timezone.utc).isoformat(),
                base_url=base, health=health, recommendation_checks=outputs, feedback_event=event,
                checks=['root enters real API mode', 'frontend health', 'model identity and count',
                        'exact artifact fingerprint and data version',
                        'search and book details', 'both ranking modes', 'per-reader reasons',
                        'favorites excluded and unique recommendations', 'finite scores and aggregation/ordering parity',
                        'matching map IDs and coordinates', 'private artifact and unsupported routes return 404'])


def local(release, seed_ids=None):
    suffix = uuid.uuid4().hex[:10]
    backend, frontend = f'tastebridge-cloud-check-api-{suffix}', f'tastebridge-cloud-check-ui-{suffix}'
    try:
        # Share one network namespace to exercise Cloud Run's localhost topology.
        docker('run', '-d', '--name', backend, '--platform', 'linux/amd64', '-p', '127.0.0.1::8080',
               '--memory=512m', '--cpus=1', release['images']['backend'])
        docker('run', '-d', '--name', frontend, '--platform', 'linux/amd64', '--network', f'container:{backend}',
               '--memory=256m', '--cpus=1', '-e', 'API_BASE_URL=http://127.0.0.1:9000',
               '-e', 'PORT=8080', release['images']['frontend'])
        running_images = {name: docker('inspect', container, '--format', '{{.Image}}')
                          for name, container in (('frontend', frontend), ('backend', backend))}
        require(all(image_id == release['image_ids'][name] for name, image_id in running_images.items()),
                'Running containers do not match the release images')
        base = 'http://' + docker('port', backend, '8080/tcp')
        for attempt in range(90):
            try:
                read_json(base, '/api/health')
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(1)
        else:
            raise RuntimeError('Packaged app did not start within 90 seconds')
        result = check(base, release, feedback=True, seed_ids=seed_ids)
        logs = docker('logs', backend)
        events = []
        for line in logs.splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and all(entry.get(k) == v for k, v in result['feedback_event'].items()):
                events.append(entry)
        require(len(events) == 1, f'Expected one feedback JSON event on stdout, found {len(events)}')
        result['checks'].append('one matching feedback event on backend stdout')
        result['feedback_log'] = events[0]
        result['image_ids'] = release['image_ids']
        result['running_image_ids'] = running_images
        result['transport'] = 'Local linux/amd64 Docker containers, shared localhost network, private port'
        (STATE / 'local-smoke.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
    finally:
        for name in (frontend, backend):
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--local', action='store_true')
    mode.add_argument('--url', help='Explicit deployed service origin to test')
    parser.add_argument('--identity-token-stdin', action='store_true',
                        help='Read an existing authorized identity token from stdin; never save it')
    parser.add_argument('--feedback', action='store_true', help='Send one test feedback event to the supplied public URL')
    parser.add_argument('--reader-a-id', help='Known catalogue ID for Reader 1; supply both reader IDs')
    parser.add_argument('--reader-b-id', help='Known catalogue ID for Reader 2; supply both reader IDs')
    args = parser.parse_args()
    if args.identity_token_stdin:
        if args.local:
            parser.error('Identity tokens are only accepted with --url')
        configure_identity_token(args.url, sys.stdin.read(16385))
    if bool(args.reader_a_id) != bool(args.reader_b_id):
        parser.error('Supply both --reader-a-id and --reader-b-id')
    seed_ids = [args.reader_a_id, args.reader_b_id] if args.reader_a_id else None
    release = json.loads((STATE / 'release.json').read_text())
    if args.local:
        local(release, seed_ids=seed_ids)
    else:
        result = check(args.url.rstrip('/'), release, args.feedback, seed_ids=seed_ids)
        result['verification_access'] = 'authorized_identity' if _identity else 'anonymous'
        (STATE / 'live-smoke.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
