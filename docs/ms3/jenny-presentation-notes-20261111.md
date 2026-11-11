# Jenny's updated MS3 speaking notes

Prepared November 11 for Jenny's application and serving contribution. This is a three-minute insert for the team's 15-minute presentation, not a replacement for the training owner's slides. The November 5 PPTX remains historical. The live serving section below is backed by the November 11 evidence. Teaching-staff access, full team training/workflow integration and the final deck remain separate.

## Slide 1 The model result reaches the right user state

**On the slide**
- Frontend validates the API contract and preserves backend scores.
- Late responses cannot replace newer selections.
- Restored votes and choices are tied to the actual model fingerprint.
- Four model files are validated before serving starts.

**Say in about 55 seconds**

My MS3 work is on the application and serving side. I connected the frontend to the recommendation API and made the state safe across requests and refreshes. The frontend keeps the backend's ranking rather than calculating another one. If an older request returns late, it cannot replace the user's newer choices. We also attach the model fingerprint to saved decisions, so a model update cannot silently reuse votes from a different model. The fingerprint identifies the bytes we loaded; it does not measure model quality.

**Open if asked:** `frontend/prototype/src/api/client.mjs`, `frontend/prototype/src/a/desk-session.mjs`, `src/backend/app/artifacts.py`. Explain why frontend validation does not replace backend validation.

## Slide 2 The exact serving model is deployed

**On the slide**
- B2 ALS; 5,000 works; exact export locked.
- Frontend and FastAPI packaged in one Cloud Run service.
- Linux/amd64 local smoke and full authenticated live smoke passed.
- 108 frontend, 124 backend and 79 integration/tool tests passed.

**Say in about 65 seconds**

Nikhil and I are responsible for deployment. One Cloud Run service now serves the frontend and internal API, using the locked 5,000-book ALS export. Both ranking modes return the expected model fingerprint. We verified the actual deployed prediction through curl and the browser, and matched requests to the ready revision's cloud logs. The live application is commit `5184a6c`, revision `tastebridge-staging-00002-vzn`. Scaling to zero reduces idle cost but adds cold-start latency, and a maximum of one instance limits throughput rather than guaranteeing availability. Authentication remains required.

**Open if asked:** `deploy/cloud-run/deploy.py`, `deploy/cloud-run/smoke.py`, `src/backend/Dockerfile`. The 51 earlier targeted tests are included in 79. Do not add them again or call local Docker IDs remote registry digests.

## Slide 3 Live evidence and remaining team checks

**On the slide**
- Real prediction response tied to URL, revision and model fingerprint.
- Authentication preserved; teaching-staff account access still to confirm.
- Cloud request logs tied to the same revision and time window.
- Final team source and evidence must land on milestone3.

**Say in about 60 seconds**

The evidence bundle now contains real prediction screenshots, the URL, revision, immutable images and model identity, plus cloud request logs and one explicit test feedback event. An authorized user can open this private service through the Cloud Run proxy. The teaching staff still need their own approved invocation access. We serve the integrated ALS model for this milestone; the new two-tower model has separate training evidence and needs its full reader-tower inference path before the app can claim to serve it. The TF asked us to justify that choice. Final team pipeline evidence, deck integration and the Canvas commit receipt are separate checks.

**Do not claim:** TF access confirmed, a successful full pipeline, a production-quality benchmark, or a Canvas submission until their own records exist. Acknowledge stronger M1 results as team-reported offline results, not measured quality of the currently served scorer.

## Refresh the old team deck before presenting

- Replace the old blanket statement that cloud reads fail. The service is now live and exact-model checks pass. Preserve the explicit distinction between directly checked project/repository policies and operator-confirmed inherited privacy.
- Use the team's November 9 tracked Vertex run for the training section, with the actual tracker screenshot and provenance. Keep historical local synthetic reproducibility as backup rather than presenting it as serverless execution.
- Confirm the full KFP execution separately. A compiled pipeline, standalone successful job, or run-ID fix does not prove a green full run.
- Architecture PR #11 is merged into main, not still open. PR #13 remains separate; the serving changes and evidence are being integrated without overwriting teammates.
- Use [actual live prediction and log evidence](evidence/deployed-serving-20261111/). Never retitle a local screenshot as cloud evidence.
- Preserve the November 12 at 10 PM ET GitHub/Canvas deadline. The TF meeting scheduled presentation for November 16.

## Be ready for individual questions

Practice short explanations of Docker dependency-layer caching, model versus data version, training versus inference, average versus least-misery ranking, held-out evaluation, W&B versus Vertex Pipelines versus Cloud Run, startup probes, cold starts, and logging versus model-quality monitoring. Know the teammates' design choices without claiming their work as your own.

Sources: [official MS3 instructions](https://harvard-iacs.github.io/2026-AC215/milestone3/); [deployed source](https://github.com/cathyliu0510/AC215_TasteBridge/tree/5184a6c836b2988f18f1f9586bb0ebf1a43f2731); [team training PR](https://github.com/cathyliu0510/AC215_TasteBridge/pull/13); [actual live verification](evidence/deployed-serving-20261111/); November 9 TF meeting at 5:33, 5:37 and 5:41–5:43.
