#!/usr/bin/env python3
"""Exercise the packaged app locally or an explicitly supplied public URL."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = Path(__file__).resolve().parent
STATE = HERE / '.state'


def request(base, path, data=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(base + path, data=body,
                                 headers={'Content-Type': 'application/json'} if body else {})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.geturl(), response.read()


def read_json(base, path, data=None):
    return json.loads(request(base, path, data)[1])


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check(base, release, feedback, seed_ids=None):
    health = read_json(base, '/api/health')
    require(health['status'] == 'ok' and health['num_books'] == release['num_books']
            and health['model_version'] == release['model_version'], f'Wrong model: {health}')
    final_url, html = request(base, '/')
    require(urllib.parse.urlparse(final_url).path == '/a/' and
            urllib.parse.parse_qs(urllib.parse.urlparse(final_url).query).get('api') == ['1'],
            f'Root did not enter the API-backed UI: {final_url}')
    require(b'TasteBridge' in html, 'Missing frontend HTML')
    require(read_json(base, '/healthz')['status'] == 'ok', 'Frontend health failed')
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
            require(bool(read_json(base, '/api/books/search?' + urllib.parse.urlencode({'q': book['title']}))),
                    'The selected catalogue title must be searchable')
        picks.append(book['book_id'])
    require(picks[0] != picks[1], 'Expected distinct reader selections')
    outputs = []
    for mode in ('least_misery', 'average'):
        result = read_json(base, '/api/recommend', dict(reader_a=picks[:1], reader_b=picks[1:], k=5, aggregation=mode))
        require(result['model_version'] == release['model_version'], 'Recommendation model mismatch')
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
    mode.add_argument('--url', help='Explicit deployed URL to test without login')
    parser.add_argument('--feedback', action='store_true', help='Send one test feedback event to the supplied public URL')
    parser.add_argument('--reader-a-id', help='Known catalogue ID for Reader 1; supply both reader IDs')
    parser.add_argument('--reader-b-id', help='Known catalogue ID for Reader 2; supply both reader IDs')
    args = parser.parse_args()
    if bool(args.reader_a_id) != bool(args.reader_b_id):
        parser.error('Supply both --reader-a-id and --reader-b-id')
    seed_ids = [args.reader_a_id, args.reader_b_id] if args.reader_a_id else None
    release = json.loads((STATE / 'release.json').read_text())
    if args.local:
        local(release, seed_ids=seed_ids)
    else:
        result = check(args.url.rstrip('/'), release, args.feedback, seed_ids=seed_ids)
        (STATE / 'public-smoke.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
