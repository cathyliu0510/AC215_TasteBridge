# Frontend / backend integration

Version A connects to the backend for book search, recommendations, separate reader reasons, galaxy coordinates, and explicit anonymous feedback. B and the public hosted prototype remain independent frontend demos.

## Run

Requires Docker with Compose. Run these commands from the repository root.

### Bundled demo catalogue

```sh
docker compose -f compose.integration.yml up --build --wait
```

Open **http://127.0.0.1:4176/a/?api=1**. This default uses **52 hand-curated books and toy vectors**. It is useful for app development, but is not evidence of a trained Goodreads model.

### Existing trained model export

First obtain the team's exported model. When the DVC pointers are available in your checkout, this downloads just the model artifacts (about 8 MB), rather than the full raw/processed dataset:

```sh
gcloud auth application-default login
dvc pull data/artifacts.dvc
```

Your Google account needs read access to the team's private DVC bucket. Until [PR #7](https://github.com/cathyliu0510/TasteBridge/pull/7) is merged, its `feature/embed-dvc-evidence` branch holds these pointers; it can be a separate data checkout. Downloading this target checks only the exported artifacts, not reproduction of the entire pipeline.

Point the app at the directory containing `books.json`, `item_embeddings.npy`, `coords_2d.npy`, and `meta.json`:

```sh
TASTEBRIDGE_ARTIFACT_DIR=/absolute/path/to/data/artifacts/current \
  docker compose -p tastebridge-real-check \
  -f compose.integration.yml -f compose.integration.real.yml up --build --wait
```

The override mounts those files **read-only** at `/artifacts/current`. A missing path fails instead of creating an empty folder or falling back to the toy model. It does not run training or modify the backend code.

Use the same app URL and check **http://127.0.0.1:4176/api/health**. For the snapshot shared on October 18, expect model `b2-als-gr-317756d1a1ad` and 5,000 books. The `data_version` field is added by [PR #5](https://github.com/cathyliu0510/TasteBridge/pull/5); if absent, record the value from the mounted `meta.json` separately. Merely seeing a working UI is not enough to identify the loaded model.

If port 4176 is occupied, set `TASTEBRIDGE_UI_PORT=4186` and use that port. To test a separate backend checkout without changing its code, also set `TASTEBRIDGE_BACKEND_DIR=/absolute/path/to/src/backend`. Record both source commits when doing so.

Stop the real-model app with the same environment variable and project name:

```sh
TASTEBRIDGE_ARTIFACT_DIR=/absolute/path/to/data/artifacts/current \
  docker compose -p tastebridge-real-check \
  -f compose.integration.yml -f compose.integration.real.yml down
```

This preserves the feedback volume. The local API is not published by the hosted prototype link.

## Check the user flow

1. Search actual titles and choose five favorites per reader. Continuing to Reader 2 should clear Reader 1's search while keeping their five picks.
2. Get recommendations, open book details and a galaxy point, and compare **Lower reader match** with **Average reader match**. Check separate reasons for each reader.
3. Confirm a shared choice. **Send anonymous feedback** submits that choice and model version only when clicked; individual interests stay local.
4. Check a search with no matches, then interrupt and restore the API. Favorites and the previous shortlist should survive an error and retry.

Save the source commit, loaded model/data versions, container status, a small input/output record, and screenshots. See [dated app evidence](ms2/frontend-api/). The older screenshots document toy data and must not be relabeled as real-data results.

## Contract and limits

| API | UI |
| --- | --- |
| `book_id`, `shelves`, `cover_url` | Opaque IDs, tags, optional cover |
| `fit_a`, `fit_b` | Signed similarities, not probabilities |
| `reasons.reader_a`, `reader_b` | References to each reader's own picks |
| `top_shelves`, `galaxy`, `position` | Reader summaries and server coordinates |
| `model_version`, `least_misery` | Feedback provenance and UI ranking mode |

Search results are hydrated before selection. Missing covers/years have text-only fallbacks. The frontend does not compute embeddings or rankings. Requests can be cancelled or retried; feedback is append-only and is not automatically retried after uncertain delivery. Undoing a local choice does not retract submitted feedback.

## MS2 scope

This app covers basic UI/backend interaction. The [course requirements](https://harvard-iacs.github.io/2026-AC215/milestone2/) also require the team's containerized data/model pipeline and its own evidence. Testing the exported model in the UI does not verify that whole pipeline.

Submit the final `milestone2` branch commit on Canvas by **October 20, 10pm ET**. Local environment evidence is accepted; a public API deployment is not a listed prerequisite. Merging a frontend PR does not redeploy the public Site or submit the milestone.
