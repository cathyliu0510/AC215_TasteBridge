# TasteBridge API Service — Specification

**Status:** DRAFT v0.4 — needs sign-off from frontend and modeling leads
**Owner:** Nikhil (backend & deployment)
**Lives in:** `src/backend/`
**Source of truth for scope:** MS1 proposal (Statement of Work)

> This file says **what** the backend must do. It is the contract between the
> frontend, the backend and the modeling pipeline. If code and this spec disagree,
> fix one of them on purpose — don't let them drift.

---

## 1. Purpose

Two readers each pick up to five favourite books. The API returns five "bridge books"
that both are likely to enjoy. Each book comes with a short reason for each reader and
the positions needed to draw the taste galaxy.

The API **serves** a trained model. It never trains one. Training happens in the
modeling pipeline, which hands the API a folder of artifacts (see §5).

## 2. Users of this API

| Caller | Uses |
|---|---|
| Frontend (screen 2: Pick your five) | `GET /books/search` |
| Frontend (screens 3–4: galaxy + explanation card) | `POST /recommend` |
| Frontend (feedback buttons) | `POST /feedback` |
| Deployment / monitoring / TFs | `GET /health`, `GET /docs` |

## 3. Conventions

- **Framework:** FastAPI with Pydantic models for every request and response.
- **Format:** JSON in, JSON out. Field names in `snake_case`.
- **Port:** `9000` (course convention). In production, use `$PORT` if set (Cloud Run).
- **CORS:** allow all origins during development. Restrict to the deployed frontend URL at MS3.
- **IDs:** `book_id` is a **string** and refers to a **work** (editions already merged), not a single edition. *(Confirm with modeling — see §9.)*
- **Auto docs:** FastAPI's `/docs` page must stay working. It serves as our API documentation for MS3.
- **Unknown request fields:** request bodies reject fields not listed here (422). This catches typos and keeps personal data out of `/feedback`.

## 4. Endpoints

### 4.1 `GET /health`

Shows the service is up, which model is loaded and which data snapshot trained it.

**Response 200**
```json
{ "status": "ok", "model_version": "b2-als-gr-317756d1a1ad", "data_version": "gr-317756d1a1ad", "num_books": 5000 }
```
`data_version` comes from `meta.json` and is `null` if the artifact does not record one.

---

### 4.2 `GET /books/search`

Search the catalogue as the user types.

**Query params**

| Name | Type | Default | Rules |
|---|---|---|---|
| `q` | string | — | must be present, 0–100 chars, matches title **or** author, case-insensitive |
| `limit` | int | 10 | 1–25 |

**Ordering:** titles that *start with* `q` come first, then other matches, each in catalogue order.

**Response 200**
```json
[
  {
    "book_id": "w_1001",
    "title": "Mistborn: The Final Empire",
    "author": "Brandon Sanderson",
    "year": 2006,
    "cover_url": null
  }
]
```
An empty (or whitespace-only) query or no matches returns `[]`, not an error.
A missing `q`, `q` over 100 chars, or `limit` out of range returns 422.

---

### 4.3 `GET /books/{book_id}`

Full details for one book (used by the explanation card).

**Response 200**
```json
{
  "book_id": "w_1001",
  "title": "Mistborn: The Final Empire",
  "author": "Brandon Sanderson",
  "year": 2006,
  "shelves": ["epic-fantasy", "heist", "magic-system"],
  "cover_url": null
}
```
**404** if the ID is unknown.

---

### 4.4 `POST /recommend`  ← the core endpoint

**Request**
```json
{
  "reader_a": ["w_1001", "w_1002", "w_1003", "w_1004", "w_1005"],
  "reader_b": ["w_2001", "w_2002", "w_2003", "w_2004", "w_2005"],
  "k": 5,
  "aggregation": "least_misery"
}
```

| Field | Rules |
|---|---|
| `reader_a`, `reader_b` | 1–5 book IDs each, no duplicates within a reader. 1–4 is allowed so we can run the proposal's robustness test. The UI still asks for 5. |
| `k` | optional, default 5, range 1–20. Fewer than `k` results are returned only if the catalogue runs out of non-seed books. |
| `aggregation` | optional, `"least_misery"` (default) or `"average"`. `"least-misery"` (the prototype's spelling) is also accepted. The response always uses `"least_misery"`. |

The same book appearing for both readers is allowed.

**Algorithm (from the proposal's Solution Direction)**
1. Taste vector per reader = mean of their books' item embeddings, then normalised to length 1.
2. `fit_a`, `fit_b` = cosine similarity of every catalogue book to each taste vector.
3. Combine:
   - `average` → `(fit_a + fit_b) / 2`
   - `least_misery` → `min(fit_a, fit_b)`
4. Exclude every seed book from either reader.
5. Return the top `k` by combined score. `score`, `fit_a` and `fit_b` are rounded to 4 decimals.

**Response 200**
```json
{
  "model_version": "b1-itemknn-2026-10-18",
  "aggregation": "least_misery",
  "top_shelves": {
    "reader_a": ["fantasy", "coming-of-age", "adventure"],
    "reader_b": ["mystery", "psychological-thriller", "twists"]
  },
  "recommendations": [
    {
      "rank": 1,
      "book": {
        "book_id": "w_3001",
        "title": "The Lies of Locke Lamora",
        "author": "Scott Lynch",
        "year": 2006,
        "shelves": ["heist", "found-family", "fantasy"],
        "cover_url": null
      },
      "score": 0.71,
      "fit_a": 0.83,
      "fit_b": 0.71,
      "reasons": {
        "reader_a": {
          "seed_id": "w_1001",
          "seed_title": "Mistborn: The Final Empire",
          "same_author": false,
          "shared_shelves": ["heist", "found-family"],
          "text": "Closest to your pick Mistborn: The Final Empire; shared shelves: heist, found-family."
        },
        "reader_b": {
          "seed_id": "w_2001",
          "seed_title": "Gone Girl",
          "same_author": false,
          "shared_shelves": ["con-artist", "unreliable-narrator"],
          "text": "Closest to your pick Gone Girl; shared shelves: con-artist, unreliable-narrator."
        }
      },
      "position": { "x": 0.12, "y": -0.40 }
    }
  ],
  "galaxy": {
    "reader_a": [ { "book_id": "w_1001", "title": "Mistborn: The Final Empire", "x": -1.20, "y": 0.30 } ],
    "reader_b": [ { "book_id": "w_2001", "title": "Gone Girl", "x": 1.10, "y": -0.20 } ],
    "bridges":  [ { "book_id": "w_3001", "title": "The Lies of Locke Lamora", "x": 0.12, "y": -0.40 } ]
  }
}
```

**Explanation rules** (proposal: "Reasons come only from shared authors, shelf tags and picked books")
- For each reader, find **their own** seed book that is closest to the recommended book (cosine similarity of item embeddings).
- The reason names that seed book. If the recommended book's author wrote any of that reader's picks, it adds `same author as one of your picks: <author>`. It then lists up to 3 shelves shared with the closest seed, in the recommended book's shelf order.
- Each reason is an object. `seed_id` and `seed_title` name the closest seed. `same_author` is true when the author wrote any of that reader's picks. `shared_shelves` holds the up-to-3 shared shelves. `text` is the ready-to-show sentence.
- `text` format: `Closest to your pick <title>[; same author as one of your picks: <author>][; shared shelves: a, b, c].`
- `top_shelves` gives each reader's 3 most common shelves across their picks (ties keep first-seen order). The UI shows it as a reader's taste summary.
- Template text only, with **no invented facts**. LLM rephrasing via RAG is a stretch goal and is not part of this spec.

**Errors**

| Code | When |
|---|---|
| 422 | Wrong shape: >5 books, 0 books, duplicates, bad `aggregation`, `k` out of range, unknown fields, a `book_id` over 64 chars |
| 404 | Any `book_id` not in the catalogue. Body: `{"detail": {"message": "...", "unknown_ids": [...]}}` listing every unknown ID. |

---

### 4.5 `POST /feedback`

Anonymous vote from the "We'd read this / Not for us" buttons.

**Request**
```json
{ "book_id": "w_3001", "vote": "would_read", "model_version": "b1-itemknn-2026-10-18" }
```
`vote` is `"would_read"` or `"not_for_us"`.

**Response 200** → `{ "ok": true }`

**Errors:** 422 for a bad `vote`, unknown fields or a `book_id` over 64 chars, 404 for an unknown `book_id`,
503 if the vote cannot be written to storage.

**Privacy (from the proposal's ethics section):** store **only** `book_id`, `vote`,
`model_version` and a timestamp. No names, IP addresses, reading lists or session IDs.
For MS2 this goes to a local JSON-lines log (`FEEDBACK_PATH`). Where it's stored at MS3 is still open (§9).

## 5. Model artifact contract (hand-off from modeling → backend)

The training pipeline writes one folder per model version. The API loads it at startup.

```
<ARTIFACT_DIR>/
  books.json           [{ "book_id", "title", "author", "shelves": [...], "year"?, "cover_url"? }]
  item_embeddings.npy  float32, shape (num_books, dim)   — row i ↔ books.json[i]
  coords_2d.npy        float32, shape (num_books, 2)     — UMAP x, y for the galaxy
  meta.json            { "model_version": "...", "created_at": "...", "data_version": "..."?, ... }
```

- `meta.json` must have a non-empty `model_version`. `data_version` is optional, but if present it must be a non-empty string. Other keys (hyperparameters, counts, `code_version`) are allowed and ignored by the API.
- **Producer:** `src/evaluation/evaluation/export.py` (Cathy, B2 ALS) writes this folder to `data/artifacts/<model_version>/` and `data/artifacts/current/`. `make serve` mounts `data/artifacts` into the backend and sets `ARTIFACT_DIR=/artifacts/current`.

- `ARTIFACT_DIR` is set by an environment variable: a local path for MS2, a GCS path for MS3.
- Any model (B0 popularity, B1 item-kNN, B2 ALS/BPR, M1 hybrid) can be served if it exports this format. Swapping models means pointing at a new folder, with no code change.
- The API must **fail fast at startup** if the three files have different row counts. It also refuses
  to start on: a missing file, duplicate `book_id`s, an empty catalogue, NaN/infinite values,
  `coords_2d.npy` without exactly 2 columns, or a `meta.json` without `model_version`.
- **Until the modeling lead delivers real artifacts, the backend ships a small sample artifact set**
  (`src/backend/sample_artifacts/`, 52 books with toy shelf-tag embeddings) so the frontend can integrate.

## 6. Non-functional requirements

| Requirement | Target | Source |
|---|---|---|
| Latency of `/recommend` | < 0.5 s per request | Proposal, objective 4 |
| One-command run | `docker compose up` brings up the API (with the frontend) | MS2 |
| Package management | `uv` only: `pyproject.toml` + `uv.lock` | MS2 / course |
| Containerised | Dockerfile in the course style (non-root user, `uv sync --frozen`) | MS2 |
| Logging | Every request logs method, path, status and duration in ms | MS3 monitoring |
| Tests | pytest. Every endpoint has a happy-path test and an error test. | MS3 |
| Coverage | ≥ 50% backend coverage at MS4, ≥ 70% at MS5 | Proposal milestones |

## 7. Scope by milestone

**MS2 (due Oct 20) — skeleton that talks to the frontend**
- [x] `/health`, `/books/search`, `/books/{id}`, `/recommend`, `/feedback` work against the **sample** artifacts
- [x] Runs locally via uv and inside Docker
- [x] Part of the team's one-command runs: `docker compose up` (backend), `compose.integration.yml` (frontend + backend), `make serve` / `make app` (trained B2 model)
- [x] Frontend successfully calls `/recommend` (evidence: `docs/ms2/frontend-api/`)
- [x] Serves the trained B2 ALS artifacts and reports their `data_version` (evidence: `docs/ms2/backend/`)

**MS3 (due Nov 12) — real model, deployed**
- [ ] Loads real baseline/M1 artifacts from GCS
- [ ] Deployed on Cloud Run, reachable by TFs; `curl` screenshot in `docs/`
- [ ] Cloud Logging set up and documented
- [ ] Endpoints documented in the README (plus `/docs`); pytest suite passing

**Later (MS4–MS5):** CI on GitHub Actions, coverage targets, Kubernetes scaling, optional LLM rephrasing of reasons, groups of 3–5 readers.

## 8. Out of scope (don't build these)

- User accounts, login or sessions
- A database (files are enough until feedback storage is decided)
- Training or retraining inside the API
- A chatbot or free-text LLM answers
- 3-D galaxy coordinates (2-D first, per the proposal)

## 9. Open questions — need answers from teammates

**Answered**

| # | Question | Answer |
|---|---|---|
| 1 | Is `book_id` the Goodreads work_id, and in what format? | Yes: the work_id as a string of digits, e.g. `"500345"` (`export.py`). The sample artifacts keep `w_` IDs. |
| 2 | Will the model export the §5 format? Which baseline first? | Yes: B2 ALS via `export.py` (128 factors, reg 50, UMAP coords). B0 and B1 have no item vectors, so they are evaluated offline only. |
| 3 | Do the §4 shapes match the frontend? | Yes, since v0.3. The frontend maps snake_case fields in `frontend/prototype/src/api/client.mjs` (`docs/backend-integration.md`). |

**Still open**

| # | Question | Ask |
|---|---|---|
| 4 | Do we want cover images? If so, where do the URLs come from? | Frontend + modeling |
| 5 | Default aggregation: `least_misery` or `average`? On real data least-misery lowers Min-Recall@10 for every model but adds long-tail books (`docs/ms2/models/README.md`). | Team, using eval results |
| 6 | Where should feedback votes be stored at MS3 (GCS file, Firestore, BigQuery)? | Team |
| 7 | Search: is simple substring matching enough for 5,000 books, or do we want typo tolerance? | Product/UX lead |
| 8 | Serving rule: cosine on unit vectors drops ALS's popularity signal. Add a popularity term, serve item-kNN, or use raw dot products? Needs one extra artifact field. | Modeling + backend (MS3) |

## 10. Changelog

- **v0.4 (2026-10-18):** `/health` and the startup log report `data_version` from `meta.json` (optional: `null` if absent, and a malformed value stops startup). Documented the B2 ALS producer (`export.py`) and `make serve`. Answered open questions 1–3; added question 8 (serving rule).
- **v0.3 (2026-10-11):** aligned with the frontend prototype (`origin/prototype/ms1-scope-and-website`). `aggregation` also accepts `"least-misery"`. Reasons are now objects (`seed_id`, `seed_title`, `same_author`, `shared_shelves`, `text`) instead of plain strings. Added `top_shelves` to the `/recommend` response, and an optional `year` to books. JSON field names stay snake_case; the frontend maps them in its API client.
- **v0.2 (2026-10-11):** moved to `src/backend/`. Clarified that an empty `q` returns `[]` (v0.1 said both "1–100 chars" and "empty returns `[]`"). Request bodies reject unknown fields and `book_id`s over 64 chars (422). `/feedback` returns 404 for unknown books and 503 on storage failure. Spelled out the reason format, the extra fail-fast artifact checks, and score rounding.
- **v0.1 (2026-10-10):** first draft from the MS1 proposal and wireframes.
