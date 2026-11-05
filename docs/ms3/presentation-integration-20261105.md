# MS3 presentation evidence integration

This manuscript integrates the November 5 team-model evidence into the existing 12-slide review and preserves its **900-second** timing. The existing PPTX remains the earlier November 4 review draft. This file provides exact replacements and speaker notes; it does not claim the binary slides were updated or natively rendered. Keep the existing visual identity and slide count.

| Slide | Seconds | Evidence/content integration |
| --- | ---: | --- |
| 1 | 45 | Replace the dated scope line with “5,000-book team model connected locally”. Retain “Cloud training, deployment and production evidence pending”. Date November 5 |
| 2 | 75 | Keep the four-file architecture. Add “Exact artifact bytes locked” and cite the identity audit rather than using the model label as proof |
| 3 | 75 | Retain the two clean synthetic reproducibility runs with their original source/hash references. Label this evidence synthetic, separately from the 5,000-book serving demo |
| 4 | 90 | Keep the train/evaluation split explanation. Distinguish synthetic smoke counts from the historical team counts: serving 9,896 retained users; historical evaluation train/tune/test 7,917/990/989. No refit occurred in November 5 verification |
| 5 | 75 | Keep synthetic metric output if it remains on the slide. Explain historical real-data evaluation separately from the evidence context; no new model-quality claim |
| 6 | 120 | Replace synthetic UI screenshots with the real-model desktop and 320px screenshots below. Visible label: “Existing team model, 5,000 books”. Demo both reader reasons, Interested, explicit choice and Back to shortlist |
| 7 | 75 | Keep API-contract scope. Use the November 5 `api-check.json` for the real-model check and identify its minimal two-ID smoke request separately from the browser's full five-book shelves |
| 8 | 60 | Update tools to 34 passing tests, including stale-lock/old-image checks. Preserve dates/scope for the existing component counts; none certify cloud execution |
| 9 | 75 | Show current lock fingerprint suffix `cb4457b668e3`. Explain old Docker model label matches while three file hashes differ. Actual current image build, service revision and staff access remain unverified |
| 10 | 60 | Retain local log as local evidence. State the actual bounded production-log query returned 403; request a real revision-linked event and access instructions |
| 11 | 75 | Keep cloud gates pending. Add current real-model serving evidence without changing serverless training, workflow or deployed-service status |
| 12 | 75 | Priority: collect/reuse existing cloud proof; authorized operator validates current images and fills genuine gaps; team reviews and submits. Keep GitHub push clarification separate from cloud permissions |

## Slide 6 replacement copy

**Existing team model in the Reading Desk**

5,000 books

Each reader sees a reference from their own favorites. Both readers mark interest before confirming a shared choice. Ranking can use the lower match or the average match.

Speaker notes:

“Today’s demo reuses the team’s October B2 export from the pinned DVC snapshot. We checked the four file hashes and served it through the latest frontend and backend. No training or new evaluation ran. The same actual HTTP contract passed for both ranking rules. The desktop and 320px phone checks cover reader reasons, two Interested responses, explicit confirmation and return to the shortlist. The choice stays on the page. We did not send feedback.”

Use [actual desktop evidence](evidence/team-serving-20261105/team-model-desktop.png), [mobile book connections](evidence/team-serving-20261105/team-model-connections-320.png) and [average-ranking evidence](evidence/team-serving-20261105/team-model-average-320.png). Keep each image's aspect ratio. The screenshot inputs are real catalogue content and example book shelves, not private reader profiles.

## Slide 9 replacement copy

**Current export identity and deployment evidence**

Locked export: `cb4457b668e3`

The old image check has the same model name but different model bytes and app sources.

Current container build and deployed revision remain pending.

Speaker notes:

“The serving export records 128 factors, regularization 50, alpha 20, 15 iterations and seed 42. We recovered and verified the team’s pinned current files. Their model name matches the old Docker report, but embeddings, coordinates and metadata hashes differ. Both app-source trees also changed. We therefore keep the old image verification as historical. The build command now accepts an exact artifact lock and stops before Docker if the staged files differ. An authorized operator still needs to build and smoke current images, inspect existing cloud work and obtain real service/revision evidence.”

Source: [identity report](evidence/identity-handoff-20261105/identity-audit-v2.json) and [operator sequence](deployment-evidence-handoff-20261105.md). This does not assert that retraining the same labels reproduces byte-identical weights on another machine.

## Historical quality context for Q&A

The historical 300-pair held-out B2 results are available separately: average Min-Recall@10 **0.0432**, least-misery **0.0236**; NDCG@10 **0.3551** and **0.1686** respectively. These are MS2 evaluation results, not November 5 measurements. The evaluation parameter values and source tree match the export's recorded implementation, but the evaluated training-user fit differs from the all-reader serving refit. The team’s historical item-kNN baseline performed better on Min-Recall@10; serving ALS does not establish that it is the best model.

Reference [historical evaluation context](evidence/identity-handoff-20261105/historical-evaluation-context.json) and [team model notes](../ms2/models/README.md). Keep synthetic slide-5 numbers separate.

## Review before the graded presentation

Replace cloud placeholders only with real training/workflow/service/log evidence. Then update the existing PPTX and speaker notes together, render every changed slide, scan the full deck for unintended changes, check native PowerPoint/Keynote rendering and rehearse the existing 15-minute timing. The current integration manuscript is ready for that evidence handoff; the deck remains a review draft.
