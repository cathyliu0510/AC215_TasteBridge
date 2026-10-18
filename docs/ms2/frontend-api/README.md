# MS2 app integration evidence

Checked October 12, 2026: A **20261012.1** against backend PR #2 (`a9f1620dc2ea3070c600f7cca5128805cc8b74a0`). This records the application skeleton with sample artifacts; it does not establish completion of the data pipeline or trained-model deliverables.

| Check | Result |
| --- | --- |
| Frontend tests | 39 passed: API client, request races, ranking state, metadata rendering and HTTP relay |
| Build | Four routes verified; root matches A; B's bundle is unchanged |
| Docker | Frontend and backend healthy together, launched with one Compose command |
| Native app | The same flow also ran with the native one-command launcher |
| Browser flow | Two readers manually searched and selected five favorites each; API returned five books and separate reasons |
| Ranking / galaxy | Both aggregation modes worked; 15 stars used server coordinates; an absent joint choice was revoked after re-ranking |
| Feedback | Only an explicit anonymous feedback action wrote one event; no reader IDs or reading lists in the record |
| Outage / recovery | Stopped the backend; kept 5/5 picks and five prior results; resumed the requested ranking with Try again |
| Empty results | Temporary five-book fixture and identical five-book profiles returned no candidates; UI retained favorites and showed an empty-state message |
| Responsive UI | Desktop, 390px and 320px layouts checked; no horizontal overflow |

The Docker stack served `sample-shelf-toy-v1`, data version `hand-curated-sample-52`. The smaller empty-result fixture was generated temporarily from five rows of those toy artifacts and is not committed. These checks measure integration behavior, not recommendation quality or a user study.

## Real-catalogue check: pending

As of October 18, the real Goodreads model has not been tested in Jenny's local frontend. The evidence below remains the 52-book toy-model run. Once the shared model artifacts are available:

- [ ] Start the frontend and backend in Docker; record `/health` model and data versions (expected data version: `gr-317756d1a1ad`).
- [ ] Search and choose five books per reader; check recommendations and book details in both ranking modes.
- [ ] Submit explicit feedback; check empty results and API outage/recovery without losing selected books.
- [ ] Save screenshots and a short run log with the commit SHA, artifact versions and local Docker environment.

## Artifacts

- [Sample input and mapped API output](api-check.json)
- [Environment, source and artifact fingerprints](verification.json)
- [Application run log](run.log)
- [Desktop](desktop.jpg), [phone](phone.jpg), [unavailable API](api-unavailable.jpg), [empty shortlist](empty-results.jpg)

See [run instructions](../../backend-integration.md#run). The checked pre-merge command used a separate backend checkout:

```sh
TASTEBRIDGE_BACKEND_DIR=../TasteBridge-backend-review/src/backend docker-compose -f compose.integration.yml up --build --wait
```

After the backend source is present at `src/backend/`, the override is unnecessary. This preview binds to localhost; the existing public website remains the independent frontend demo.

Codex assisted with the adapter, UI wiring, launchers, tests and documentation. The browser and container checks above verify runtime behavior; human code review is still pending in the frontend PR.

A's subsequent [20261012.2 visual update](style-20261012.2/) applies B's palette and type while retaining this API flow. The original screenshots and fingerprints above remain the dated 20261012.1 record.

The [two-branch review recipe](../../backend-integration.md#run) was also checked from fresh remote clones on October 12. An isolated Docker stack returned five recommendations and 15 galaxy points, with both services healthy. [Versions and result summary](fresh-checkouts.json) · [build/run log](fresh-checkouts.log). This check submitted no feedback and left the existing preview running.

On October 13, a [local merge rehearsal](merge-rehearsal.json) combined both PRs without conflicts and ran the integration Compose file using its default `src/backend/` path. Both containers were healthy; search, book details, four page routes, and both ranking modes passed API checks, each returning five recommendations and 15 galaxy points. This used toy artifacts and submitted no feedback; neither PR was merged on GitHub.
