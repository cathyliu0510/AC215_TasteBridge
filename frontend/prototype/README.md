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
node --test tools/verify-ranking.mjs
node --test tools/verify-api-client.mjs
node --test tools/verify-api-desk.mjs tools/verify-server.mjs
python3 -m http.server 4175 --bind 127.0.0.1 --directory dist
```

Open http://127.0.0.1:4175/ for A, `/b/` for B, and `/project/` for the scope page.

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
