import test from 'node:test';
import assert from 'node:assert/strict';
import {
  TasteBridgeClient, TasteBridgeApiError, mapApiBook, makeRecommendationRequest,
  mapRecommendationResponse, makeFeedbackRequest
} from '../src/api/client.mjs';

const a = ['a1', 'a2', 'a3', 'a4', 'a5'];
const b = ['b1', 'b2', 'b3', 'b4', 'b5'];
const request = makeRecommendationRequest(a, b);
const point = (id, x = 0, y = 0) => ({ book_id: id, title: id, x, y });
const reason = id => ({ seed_id: id, seed_title: id, same_author: false, shared_shelves: ['heist'], text: `Shared shelf with ${id}.` });
const response = () => ({
  model_version: 'sample-shelf-toy-v1', aggregation: 'least_misery',
  top_shelves: { reader_a: ['fantasy'], reader_b: ['mystery'] },
  recommendations: [{ rank: 1,
    book: { book_id: 'c1', title: 'A bridge', author: 'An author', shelves: ['heist'], cover_url: null },
    score: -.1, fit_a: -.1, fit_b: .8,
    reasons: { reader_a: reason(a[0]), reader_b: reason(b[0]) }, position: { x: .12, y: -.4 }
  }],
  galaxy: { reader_a: a.map(id => point(id)), reader_b: b.map(id => point(id)), bridges: [point('c1', .12, -.4)] }
});
const reply = (value, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => value });
const clientFor = fetchImpl => new TasteBridgeClient({ baseUrl: 'http://127.0.0.1:9000', fetchImpl });

test('maps optional canonical artifact fingerprints in health and recommendations without inventing identity',async()=>{
 const fingerprint='0123456789abcdef'.repeat(4);
 for(const value of [undefined,null,fingerprint]){
  const health=await clientFor(async()=>reply({status:'ok',model_version:'same-label',num_books:5000,...(value===undefined?{}:{artifact_fingerprint:value})})).health();
  const mapped=mapRecommendationResponse({...response(),...(value===undefined?{}:{artifact_fingerprint:value})},request);
  assert.equal(health.artifactFingerprint,value??null);assert.equal(mapped.artifactFingerprint,value??null);
  assert.equal(health.modelVersion,'same-label');
 }
});

test('rejects malformed, uppercase, truncated and structured artifact fingerprints',async()=>{
 for(const artifact_fingerprint of ['a'.repeat(63),'a'.repeat(65),'A'.repeat(64),'g'.repeat(64),1,{hashes:{}}]){
  assert.throws(()=>mapRecommendationResponse({...response(),artifact_fingerprint},request),/artifact fingerprint/);
  await assert.rejects(clientFor(async()=>reply({status:'ok',model_version:'same-label',num_books:5000,artifact_fingerprint})).health(),/artifact fingerprint/);
 }
});

test('sends exactly five opaque IDs, supports overlap between readers, and normalizes aggregation', () => {
  assert.deepEqual(makeRecommendationRequest(a, a, 'least-misery'), { reader_a: a, reader_b: a, k: 5, aggregation: 'least_misery' });
  const value = makeRecommendationRequest(a, b, 'average');
  value.reader_a.pop();
  assert.equal(a.length, 5);
  assert.equal(value.aggregation, 'average');
});

test('rejects incomplete picks, duplicate picks, oversized IDs and unknown modes', () => {
  for (const [x, y, mode] of [[a.slice(1), b], [['a1', 'a1', 'a3', 'a4', 'a5'], b], [[...a.slice(1), 'x'.repeat(65)], b], [a, b, 'unknown']])
    assert.throws(() => makeRecommendationRequest(x, y, mode), TasteBridgeApiError);
});

test('maps separate reasons, shelf evidence, top shelves and server coordinates without changing scores or input', () => {
  const input = response(), original = structuredClone(input);
  const mapped = mapRecommendationResponse(input, request);
  assert.equal(mapped.results[0].book.id, 'c1');
  assert.equal(mapped.results[0].book.year, null);
  assert.equal(mapped.results[0].book.coverUrl, null);
  assert.equal(mapped.results[0].fitA, -.1);
  assert.equal(mapped.results[0].reasons.a.seedId, 'a1');
  assert.equal(mapped.results[0].reasons.b.seedId, 'b1');
  assert.deepEqual(mapped.results[0].position, { x: .12, y: -.4 });
  assert.deepEqual(mapped.topShelves, { a: ['fantasy'], b: ['mystery'] });
  assert.equal(mapped.mode, 'least-misery');
  assert.deepEqual(input, original);
});

test('accepts fewer than five recommendations and an empty shortlist', () => {
  const input = response();
  assert.equal(mapRecommendationResponse(input, request).results.length, 1);
  input.recommendations = []; input.galaxy.bridges = [];
  assert.deepEqual(mapRecommendationResponse(input, request).results, []);
});

test('rejects a reason pointing to the other reader and shelves absent from the recommendation', () => {
  const input = response(); input.recommendations[0].reasons.reader_a.seed_id = 'b1';
  assert.throws(() => mapRecommendationResponse(input, request), /different reader/);
  input.recommendations[0].reasons.reader_a.seed_id = 'a1';
  input.recommendations[0].reasons.reader_a.shared_shelves = ['invented shelf'];
  assert.throws(() => mapRecommendationResponse(input, request), /absent/);
});

test('rejects seed recommendations, duplicate results, wrong aggregation and malformed scores', () => {
  for (const mutate of [
    value => { value.recommendations[0].book.book_id = a[0]; },
    value => { value.recommendations.push({ ...structuredClone(value.recommendations[0]), rank: 2 }); },
    value => { value.aggregation = 'average'; },
    value => { value.recommendations[0].fit_a = NaN; },
    value => { value.recommendations[0].rank = 2; }
  ]) {
    const input = response(); mutate(input);
    assert.throws(() => mapRecommendationResponse(input, request), TasteBridgeApiError);
  }
});

test('rejects missing seed points and mismatched positions instead of drawing a misleading galaxy', () => {
  const input = response(); input.galaxy.reader_a.pop();
  assert.throws(() => mapRecommendationResponse(input, request), /Galaxy IDs/);
  input.galaxy.reader_a = a.map(id => point(id)); input.galaxy.bridges[0].x = .5;
  assert.throws(() => mapRecommendationResponse(input, request), /positions disagree/);
});

test('handles absent years/covers and does not allow executable cover URLs', () => {
  const book = { book_id: 'unfamiliar-id', title: 'Unknown title', author: 'Author' };
  assert.deepEqual(mapApiBook(book), { id: book.book_id, title: book.title, author: book.author, year: null, coverUrl: null, tags: [] });
  assert.throws(() => mapApiBook({ ...book, cover_url: 'javascript:alert(1)' }), /cover URL/);
  assert.throws(() => mapApiBook({ ...book, year: '2006' }), /year/);
});

test('feedback keeps the returned model version and excludes individual votes and personal fields', () => {
  const action = { bookId: 'c1', vote: 'would_read', modelVersion: 'sample-shelf-toy-v1', reader: 'a', seeds: a };
  assert.deepEqual(makeFeedbackRequest(action), { book_id: 'c1', vote: 'would_read', model_version: 'sample-shelf-toy-v1' });
  assert.equal(makeFeedbackRequest({ ...action, vote: 'not_for_us' }).vote, 'not_for_us');
  for (const vote of ['yes', 'no', 'unsure']) assert.throws(() => makeFeedbackRequest({ ...action, vote }), /joint/);
  assert.throws(() => makeFeedbackRequest({ ...action, modelVersion: '' }), /model version/);
});

test('explicit feedback sends the validated recommendation fingerprint and omits it for legacy responses',async()=>{
 const fingerprint='0123456789abcdef'.repeat(4),bodies=[];
 const client=clientFor(async(_url,options)=>{bodies.push(JSON.parse(options.body));return reply({ok:true});});
 for(const artifactFingerprint of [fingerprint,null,undefined])await client.feedback({bookId:'c1',vote:'would_read',modelVersion:'same-label',artifactFingerprint,reader:'a',seeds:a});
 assert.deepEqual(bodies[0],{book_id:'c1',vote:'would_read',model_version:'same-label',artifact_fingerprint:fingerprint});
 for(const body of bodies.slice(1))assert.deepEqual(body,{book_id:'c1',vote:'would_read',model_version:'same-label'});
 for(const artifactFingerprint of ['bad','A'.repeat(64),{hashes:{}}])assert.throws(()=>makeFeedbackRequest({bookId:'c1',vote:'would_read',modelVersion:'same-label',artifactFingerprint}),/artifact fingerprint/);
 assert.equal(bodies.length,3,'Invalid fingerprints must fail before any transport call.');
});

test('search URL-encodes input and preserves API IDs without sending cookies', async () => {
  let call;
  const client = clientFor(async (url, options) => { call = { url, options }; return reply([{ book_id: 'w_1001', title: 'Mistborn', author: 'Sanderson', cover_url: null }]); });
  const books = await client.searchBooks('title & author', { limit: 25 });
  const url = new URL(call.url);
  assert.equal(url.searchParams.get('q'), 'title & author');
  assert.equal(url.searchParams.get('limit'), '25');
  assert.equal(call.options.credentials, 'omit');
  assert.equal(books[0].id, 'w_1001');
  await assert.rejects(client.searchBooks('x'.repeat(101)), /100 characters/);
});

test('POST recommend uses the correct contract and never puts reading lists in the URL', async () => {
  let call;
  const client = clientFor(async (url, options) => { call = { url, options }; return reply(response()); });
  await client.recommend(a, b);
  assert.equal(call.url, 'http://127.0.0.1:9000/recommend');
  assert.equal(call.options.method, 'POST');
  assert.deepEqual(JSON.parse(call.options.body), request);
});

test('reports all unknown IDs from 404 responses and structured 422 validation failures', async () => {
  const unknown = clientFor(async () => reply({ detail: { unknown_ids: ['missing-a', 'missing-b'] } }, 404));
  await assert.rejects(unknown.recommend(a, b), error => error.status === 404 && error.kind === 'http' && error.unknownIds.join(',') === 'missing-a,missing-b');
  const invalid = clientFor(async () => reply({ detail: [{ loc: ['body', 'reader_a'], msg: 'error' }] }, 422));
  await assert.rejects(invalid.recommend(a, b), error => error.status === 422 && /selected books/.test(error.message));
});

test('reports 503 without retrying append-only feedback', async () => {
  let calls = 0;
  const client = clientFor(async () => { calls++; return reply({ detail: 'unavailable' }, 503); });
  await assert.rejects(client.feedback({ bookId: 'c1', vote: 'would_read', modelVersion: 'sample-shelf-toy-v1' }), error => error.status === 503);
  assert.equal(calls, 1);
});

test('rejects malformed JSON and unexpected successful responses', async () => {
  const malformed = clientFor(async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError(); } }));
  await assert.rejects(malformed.health(), /unreadable/);
  const wrong = clientFor(async () => reply({ book_id: 'wrong', title: 'Wrong', author: 'Author', shelves: [] }));
  await assert.rejects(wrong.book('wanted'), /different book/);
});

test('reports network failure', async () => {
  const client = clientFor(async () => { throw new TypeError('Failed to fetch'); });
  await assert.rejects(client.health(), error => error.kind === 'network');
});

test('keeps the native browser fetch receiver when the function is supplied as a dependency', async () => {
  const client = clientFor(async function () {
    assert.equal(this, globalThis);
    return reply({ status: 'ok', model_version: 'sample-v1', num_books: 52 });
  });
  assert.equal((await client.health()).numBooks, 52);
});

test('service outages do not describe search or health failures as feedback failures', async () => {
  const client = clientFor(async () => reply({ detail: 'unavailable' }, 503));
  await assert.rejects(client.health(), error => error.status === 503 && /book service/.test(error.message));
});

test('cancels a slow request on timeout', async () => {
  const client = new TasteBridgeClient({ baseUrl: 'http://127.0.0.1:9000', timeoutMs: 10,
    fetchImpl: async (_url, { signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true })) });
  await assert.rejects(client.health(), error => error.kind === 'timeout');
});

test('caller cancellation stays an AbortError so superseded searches can be ignored', async () => {
  const controller = new AbortController();
  const client = clientFor(async (_url, { signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true })));
  const pending = client.searchBooks('Mistborn', { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, error => error.name === 'AbortError');
});
