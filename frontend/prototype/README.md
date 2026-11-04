# TasteBridge frontend prototype

[Live prototype](https://tastebridge-prototype.landenini.chatgpt.site/) · [Project scope](https://tastebridge-prototype.landenini.chatgpt.site/project/)

A (Reading Desk) is the preferred interface; B (Book Journey) is the comparison. Both demonstrate two readers choosing five favorites each, exploring five new bridge books, inspecting separate reasons, and making a reversible shared choice. Project links carry the selected favorite IDs and ranking mode back to the demo; votes and joint choices remain page-local.

The standalone demo uses 23 curated sample books and deterministic theme vectors. A's optional connected mode now calls the backend's SPEC v0.3 API for search, recommendations, reasons and galaxy coordinates. The default Docker app uses 52 sample books and toy vectors. The real-model Compose override can instead mount the team's exported Goodreads model. Accounts and synchronized reading rooms are not implemented. See the [integration guide](../../docs/backend-integration.md) and [MS2 app evidence](../../docs/ms2/frontend-api/).

The project overview follows the final three-page MS1 proposal shared by the team. Data caps, model comparison, reader-study design, performance criteria, and later milestones are labeled as planned work or targets. It omits architecture alternatives, stretch goals, and later meeting suggestions that have not been adopted. Submission or instructor-approval status is not asserted.

## Build and run

Requires Node.js. No package installation is needed.

```sh
node scripts/build-prototype.mjs
node scripts/verify-release.mjs
node --test tools/verify-*.mjs
python3 -m http.server 4175 --bind 127.0.0.1 --directory dist
```

Open http://127.0.0.1:4175/ for A, `/b/` for B, and `/project/` for the scope page.

### Trained-synthetic provenance 20261104.5

The connected footer identifies B2 exports whose model identity is explicitly synthetic. The [complete local integration](../../docs/ms3/reproduce.md) trained the existing B2 model twice, served it through the actual API/relay and exercised the UI at 320px. [Model identity, actual screenshots and test evidence](../../docs/ms3/evidence/local-integration-20261104/). The frontend suite now has 82 passing tests. The hosted static Site remains unchanged.

### Local search recovery 20261104.4

Author shortcuts and search recovery controls now respect connection/pick loading. All clear-search paths cancel the previous request and debounce timer, restore the catalogue and return focus without changing either shelf. The current suite has 81 passing tests. [Local flow checks, Chrome limitation and current MS3 state](../../docs/ms3/local-continuation-20261104.md). This local revision has not replaced the hosted `20261104.3` preview.

### Book connections 20261104.3

Book connections now starts with the current recommendation and the two readers' actual reference books and shared themes. Named controls expose all five recommendations. The original coordinate plot is an optional similarity view; it has no geographic meaning, decorative boundaries or inferred clusters. Mobile secondary controls are compact, responses and explicit shared-choice state stay visible, and dialog focus returns to an available relation action.

An independent UX specialist reviewed desktop, 390px and 320px results. All 80 tests pass; actual browser checks include long titles, reference exploration, confirmation, revocation and the 52-book sample API. [Current UX review, screenshots and downloadable offline preview](../../docs/ms3/connections-ux-20261104.md).

### Reading Desk 20261104.2

A now uses a light mist canvas, dark ink, spruce shared actions and blue/purple reader identities. Instrument Serif is reserved for main headings and book titles; Geist carries functional headings, controls and body text. Control spacing, borders, radii and states are consistent across selection, recommendations, map, dialogs and recovery screens. Motion supports book selection, detail paging and shared-choice feedback; system and application reduced-motion rules remain supported.

A dedicated designer and an independent reviewer checked the actual result and iterated on desktop density, dialog actions, reader badges, disabled controls and selected hover states. [Current screenshots, review and verification](../../docs/ms3/design-review-20261104.md).

At this intermediate release, Shortlist and Taste map became peer views. The projection gained a persistent book inspector, direct title navigation, readable numbered callouts, labeled zoom controls and a phone selection summary. The original projected coordinates and model scores are preserved; displaced numbered annotations use short leaders back to the actual book positions. Release `20261104.3`, above, moves the projection into the optional similarity view within Book connections.

Selection has actionable empty slots, clear search, reader-specific progress and a guided connected-catalogue empty state. Results combine each reader's reference and similarity in one place, with an explicit View reasons & respond action. Busy-state navigation, stage changes, dialog paging and map focus recovery have regression coverage. Version B remains the comparison interface.

[Behavior changes, browser checks and earlier before/after screenshots](../../docs/ms3/ux-refinement-20261104.md).

### Check the connected app setup

From `frontend/prototype`, check local prerequisites before launching the frontend and API:

```sh
node scripts/check-setup.mjs
node scripts/dev.mjs
```

The preflight requires Node 20 or newer and `uv` on PATH. It checks the backend source, configured port ranges and required artifact files without starting services or accessing cloud accounts. It does not read `.env` files, install packages, download data, or validate artifact contents.

The connected launcher repeats these checks before rebuilding files or starting services. Invalid options and port settings fail before either step. Ctrl-C stops startup and both services; a backend exit also closes the frontend. The backend performs full artifact validation at startup; `uv run` may synchronize packages when the app is launched.

The default backend is `src/backend` at the repository root, with its bundled 52-book toy catalogue. A missing real-model export is informational and does not block local UI work. For a separate checkout, pass the same `--backend PATH` to both commands; relative paths are resolved from the repository root. `TASTEBRIDGE_BACKEND_DIR` is also supported, and `--backend` takes precedence.

| Setting | Default | Scope |
| --- | --- | --- |
| `TASTEBRIDGE_UI_PORT` | `4176` | Connected frontend on `127.0.0.1` |
| `TASTEBRIDGE_API_PORT` | `9016` | Local backend on `127.0.0.1`; must differ from UI port |
| `ARTIFACT_DIR` | Backend's `sample_artifacts` | A local folder; relative paths resolve from the backend directory |
| `TASTEBRIDGE_HOST` | `127.0.0.1` | Standalone `scripts/serve.mjs` only; the connected launcher always uses loopback |

After an authorized DVC pull or a completed training export, `ARTIFACT_DIR=../../data/artifacts/current` selects the trained artifacts for the local launcher. The preflight only checks file presence; it does not establish model provenance, bucket access, deployment or M3 completion. See the [root instructions](../../README.md#run-the-app) for obtaining the real export separately.

Use `node scripts/dev.mjs --help` for launcher usage. The standalone server and Docker image use `TASTEBRIDGE_HOST`; an ambient `HOST` from a shell or preview environment is ignored. Docker explicitly binds to `0.0.0.0` so its published port is reachable.

Use `node scripts/check-setup.mjs --json` for a machine-readable report. A failed required check exits with status 1. Run prerequisite, configuration and shutdown checks with `node --test tools/verify-setup.mjs tools/verify-launcher.mjs`.

Edit src/a/ and src/b/ for the independent interfaces, and pages/project.html for project content. The build creates self-contained HTML in dist/, embedding the included fonts and original illustrations. Typeface license files are in each version's shared/fonts directory and are preserved in the HTML bundles.

Keep full dataset downloads, credentials, personal information, and private team messages out of this folder. New project directions should be discussed before being represented as adopted plans.

The shared Site is published separately by its owner. Merging this PR does not automatically deploy the Site or change the project scope.

## Reading Desk style 20261012.2

A now shares B's deep green, warm cream and champagne palette, Instrument Serif / Geist typography, and rounded primary controls. Search, recommendations, per-reader reasons, choices and server-provided galaxy coordinates keep their existing behavior. [Visual checks](../../docs/ms2/frontend-api/style-20261012.2/) cover desktop and phone layouts; 39 existing frontend tests passed.

## Connected A 20261012.1

With backend PR #2's source available, run `node scripts/dev.mjs --backend path/to/src/backend` from this directory. This builds the frontend and launches both services. `/a/?api=1` uses the same-origin `/api` relay; `/a/?api=0` keeps the offline demo. The root `compose.integration.yml` also runs the pair together in Docker.

API mode uses returned IDs, hydrates search results, preserves server scores/coordinates, and supports missing metadata, empty results, cancellation and retry. Interests remain local; explicit anonymous feedback sends only a confirmed joint choice. The public Site and downloaded HTML continue to use the independent demo by default. B is unchanged.

## Reading Desk iteration 20261008.2

A now has a three-step reader handoff, recovery when a favorite is missing from the sample catalogue, equal-sized recommendation cards with separate reader overlap summaries, and core reasons before optional connection details. Ranking changes preserve responses and an explicitly confirmed choice for books that remain in the five. Editing favorites still clears the previous decision.

Selection feedback, scroll reveals, book-detail transitions, and sorting motion support the current task. System reduced-motion preferences disable this motion. The phone shelf reserves its measured height instead of relying on fixed spacing.

The task personas and review record are in docs/ux-iteration-20261008.2.json. They are design hypotheses; no interviews or usability study have been conducted. B remains at 20261008.1, and the MS1 project scope is unchanged.

## Validation

All four routes pass bundled JavaScript and metadata checks. Nine ranking-state tests cover retained opinions, removed candidates, and explicit confirmation. Browser checks cover missing-book recovery, sample replacement, separate reasons, keyboard-safe voting, retained interests after sorting, clearing decisions after favorite edits, manual shortlist sharing, and 320px/390px phone layouts. No console errors were observed. These checks verify frontend behavior; they do not measure recommendation quality or model performance.
