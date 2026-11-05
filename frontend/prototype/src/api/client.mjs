// SPEC v0.3 adapter. API book IDs are opaque; never translate fixture slugs by
// title, and never recompute server scores or galaxy coordinates in the browser.
export class TasteBridgeApiError extends Error {
  constructor(message, { kind = 'contract', status = null, unknownIds = [] } = {}) {
    super(message);
    this.name = 'TasteBridgeApiError';
    Object.assign(this, { kind, status, unknownIds });
  }
}

const fail = message => { throw new TasteBridgeApiError(message); };
const record = (value, name) => value && typeof value === 'object' && !Array.isArray(value)
  ? value : fail(`Invalid API ${name}.`);
const string = (value, name) => typeof value === 'string' && value.length
  ? value : fail(`Invalid API ${name}.`);
const list = (value, name) => Array.isArray(value) ? value : fail(`Invalid API ${name}.`);
const strings = (value, name) => list(value, name).map(item => string(item, name));
const number = (value, name) => Number.isFinite(value) ? value : fail(`Invalid API ${name}.`);
const id = value => {
  const text = string(value, 'book ID');
  if ([...text].length > 64) fail('A book ID must have at most 64 characters.');
  return text;
};
const modelVersion = value => {
  const text = string(value, 'model version');
  if ([...text].length > 128) fail('A model version must have at most 128 characters.');
  return text;
};
const artifactFingerprint = value => {
  // Older backends can serve recommendations without a verified file identity.
  if (value === undefined || value === null) return null;
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value)) fail('Invalid API artifact fingerprint.');
  return value;
};
const modeToApi = mode => mode === 'least-misery' || mode === 'least_misery'
  ? 'least_misery' : mode === 'average' ? 'average' : fail('Unknown ranking method.');
const position = value => {
  const point = record(value, 'position');
  return { x: number(point.x, 'x coordinate'), y: number(point.y, 'y coordinate') };
};

export function mapApiBook(value, { full = false } = {}) {
  const book = record(value, 'book');
  const year = book.year ?? null;
  if (year !== null && !Number.isInteger(year)) fail('Invalid API publication year.');
  const coverUrl = book.cover_url ?? null;
  if (coverUrl !== null) {
    if (typeof coverUrl !== 'string') fail('Invalid API cover URL.');
    let url;
    try { url = new URL(coverUrl); } catch { fail('Invalid API cover URL.'); }
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password)
      fail('Invalid API cover URL.');
  }
  return {
    id: id(book.book_id), title: string(book.title, 'title'),
    author: string(book.author, 'author'), year, coverUrl,
    // Search responses are summaries. Fetch /books/{id} before showing evidence.
    tags: full ? strings(book.shelves, 'shelves') : book.shelves ? strings(book.shelves, 'shelves') : []
  };
}

function mapReason(value, seeds, bookTags) {
  const reason = record(value, 'reason'), seedId = id(reason.seed_id);
  if (!seeds.includes(seedId)) fail('A reason references a different reader’s favorites.');
  if (typeof reason.same_author !== 'boolean') fail('Invalid API author evidence.');
  const tags = strings(reason.shared_shelves, 'shared shelves');
  if (tags.some(tag => !bookTags.includes(tag))) fail('A reason names a shelf absent from its book.');
  return {
    seedId, seedTitle: string(reason.seed_title, 'seed title'),
    sameAuthor: reason.same_author, tags, text: string(reason.text, 'reason text'),
    source: 'Catalogue metadata.'
  };
}

function pointsFor(value, expectedIds) {
  const points = list(value, 'galaxy points').map(raw => {
    const point = record(raw, 'galaxy point');
    return { id: id(point.book_id), title: string(point.title, 'galaxy title'), ...position(point) };
  });
  const ids = points.map(point => point.id);
  if (new Set(ids).size !== ids.length || ids.length !== expectedIds.length ||
      expectedIds.some(bookId => !ids.includes(bookId))) fail('Galaxy IDs do not match the selection.');
  return points;
}

export function makeRecommendationRequest(a, b, mode = 'least-misery') {
  for (const seeds of [a, b]) {
    if (!Array.isArray(seeds) || seeds.length !== 5 || new Set(seeds).size !== 5)
      fail('Choose five different books for each reader.');
    seeds.forEach(id);
  }
  return { reader_a: [...a], reader_b: [...b], k: 5, aggregation: modeToApi(mode) };
}

export function mapRecommendationResponse(value, request) {
  const body = record(value, 'recommendation response');
  const aggregation = modeToApi(body.aggregation);
  if (aggregation !== request.aggregation) fail('The API returned a different ranking method.');
  const model = modelVersion(body.model_version), shelves = record(body.top_shelves, 'top shelves');
  const seeds = new Set([...request.reader_a, ...request.reader_b]);
  const results = list(body.recommendations, 'recommendations').map((raw, index) => {
    const item = record(raw, 'recommendation'), book = mapApiBook(item.book, { full: true });
    if (seeds.has(book.id)) fail('The API recommended a selected favorite.');
    if (item.rank !== index + 1) fail('Invalid API recommendation rank.');
    const reasons = record(item.reasons, 'reader reasons');
    return {
      rank: item.rank, book, score: number(item.score, 'score'),
      fitA: number(item.fit_a, 'Reader 1 score'), fitB: number(item.fit_b, 'Reader 2 score'),
      reasons: {
        a: mapReason(reasons.reader_a, request.reader_a, book.tags),
        b: mapReason(reasons.reader_b, request.reader_b, book.tags)
      },
      position: position(item.position)
    };
  });
  const resultIds = results.map(result => result.book.id);
  if (results.length > request.k || new Set(resultIds).size !== resultIds.length)
    fail('Invalid API shortlist length or duplicate book.');
  const rawGalaxy = record(body.galaxy, 'galaxy');
  const galaxy = {
    a: pointsFor(rawGalaxy.reader_a, request.reader_a),
    b: pointsFor(rawGalaxy.reader_b, request.reader_b),
    bridges: pointsFor(rawGalaxy.bridges, resultIds)
  };
  for (const result of results) {
    const point = galaxy.bridges.find(node => node.id === result.book.id);
    if (point.x !== result.position.x || point.y !== result.position.y)
      fail('The recommendation and galaxy positions disagree.');
  }
  return {
    modelVersion: model, artifactFingerprint: artifactFingerprint(body.artifact_fingerprint), mode: aggregation === 'average' ? 'average' : 'least-misery',
    topShelves: { a: strings(shelves.reader_a, 'Reader 1 shelves'), b: strings(shelves.reader_b, 'Reader 2 shelves') },
    results, galaxy
  };
}

export function makeFeedbackRequest({ bookId, vote, modelVersion: model, artifactFingerprint: fingerprint }) {
  // An explicit joint action only. Individual yes/no/unsure answers stay local.
  if (!['would_read', 'not_for_us'].includes(vote)) fail('Choose an explicit joint feedback action.');
  const verified = artifactFingerprint(fingerprint);
  return { book_id: id(bookId), vote, model_version: modelVersion(model), ...(verified ? { artifact_fingerprint: verified } : {}) };
}

export class TasteBridgeClient {
  constructor({ baseUrl, fetchImpl = globalThis.fetch, timeoutMs = 10000 }) {
    const url = new URL(baseUrl);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash)
      fail('Provide a plain HTTP or HTTPS API address.');
    if (typeof fetchImpl !== 'function' || !Number.isFinite(timeoutMs) || timeoutMs <= 0)
      fail('Invalid API client configuration.');
    this.baseUrl = url.href.replace(/\/$/, '');
    // Browsers require window.fetch's receiver to be Window. Node permits the
    // unbound function, so an API-only test would not catch this difference.
    this.fetchImpl = (url, options) => fetchImpl.call(globalThis, url, options);
    this.timeoutMs = timeoutMs;
  }

  async request(path, { method = 'GET', body, signal } = {}) {
    if (signal?.aborted) throw signal.reason ?? new DOMException('Cancelled', 'AbortError');
    const controller = new AbortController();
    const cancel = () => controller.abort(signal.reason);
    signal?.addEventListener('abort', cancel, { once: true });
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, this.timeoutMs);
    try {
      const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method, credentials: 'omit', signal: controller.signal,
        headers: body ? { 'Content-Type': 'application/json' } : {},
        ...(body ? { body: JSON.stringify(body) } : {})
      });
      let value;
      try { value = await response.json(); } catch {
        if (controller.signal.aborted) throw controller.signal.reason;
        throw new TasteBridgeApiError('The API returned an unreadable response.', { status: response.status });
      }
      if (!response.ok) {
        const unknownIds = response.status === 404 && Array.isArray(value?.detail?.unknown_ids)
          ? value.detail.unknown_ids.filter(item => typeof item === 'string') : [];
        const message = response.status === 404 ? 'Some books are unavailable. Search the API catalogue again.'
          : response.status === 422 ? 'Check the selected books and ranking method.'
          : response.status === 503 && path === '/feedback' ? 'The API could not save this feedback. Try again.'
          : response.status >= 500 ? 'The book service is unavailable. Try again.'
          : 'The API request failed. Try again.';
        throw new TasteBridgeApiError(message, { kind: 'http', status: response.status, unknownIds });
      }
      return value;
    } catch (error) {
      if (signal?.aborted) throw signal.reason ?? new DOMException('Cancelled', 'AbortError');
      if (timedOut) throw new TasteBridgeApiError('The API took too long. Try again.', { kind: 'timeout' });
      if (error instanceof TasteBridgeApiError) throw error;
      throw new TasteBridgeApiError('Cannot reach the API. Check that it is running.', { kind: 'network' });
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', cancel);
    }
  }

  async health(options) {
    const value = record(await this.request('/health', options), 'health');
    if (value.status !== 'ok' || !Number.isInteger(value.num_books) || value.num_books < 1)
      fail('Invalid API health response.');
    return { status: 'ok', modelVersion: modelVersion(value.model_version), artifactFingerprint: artifactFingerprint(value.artifact_fingerprint), numBooks: value.num_books };
  }

  async searchBooks(query, { limit = 10, signal } = {}) {
    if (typeof query !== 'string' || [...query].length > 100 || !Number.isInteger(limit) || limit < 1 || limit > 25)
      fail('Use a search of at most 100 characters and a limit from 1 to 25.');
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    return list(await this.request(`/books/search?${params}`, { signal }), 'search results').map(value => mapApiBook(value));
  }

  async book(bookId, options) {
    const expected = id(bookId);
    const book = mapApiBook(await this.request(`/books/${encodeURIComponent(expected)}`, options), { full: true });
    if (book.id !== expected) fail('The API returned a different book.');
    return book;
  }

  async recommend(a, b, mode = 'least-misery', options = {}) {
    const request = makeRecommendationRequest(a, b, mode);
    const value = await this.request('/recommend', { ...options, method: 'POST', body: request });
    return mapRecommendationResponse(value, request);
  }

  async feedback(action, options = {}) {
    const value = await this.request('/feedback', { ...options, method: 'POST', body: makeFeedbackRequest(action) });
    if (value?.ok !== true) fail('The API did not confirm that feedback was saved.');
    return { ok: true };
  }
}
