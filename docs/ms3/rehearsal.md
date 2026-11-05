# TF presentation rehearsal

[Editable review deck](presentation/TasteBridge-MS3-review.pptx) · [Matching speaker notes](presentation-source.md) · [Final file/render verification](evidence/overnight-20261105/presentation-qa/visual-review.json).

The 12 slides total **900 seconds**. All final slides were rendered and individually inspected using Artifact Tool. Native PowerPoint/Keynote rendering remains unverified. Cloud cells remain incomplete; replace them with actual evidence before the graded presentation. Speaker allocation is a team decision.

| Slide | Time | Main point |
| --- | --- | --- |
| 1. Scope | 0:45 | Existing 5,000-book model works locally; cloud proof pending |
| 2. Model-to-UI path | 1:15 | Four locked files drive the API and interface |
| 3. Reproducibility | 1:15 | Two historical synthetic runs, exact source/input/output provenance |
| 4. Fits | 1:30 | Evaluation fits training readers; serving refits all retained readers |
| 5. Metrics | 1:15 | Historical synthetic 20-pair table, no Goodreads quality claim |
| 6. Actual UI | 2:00 | Both reasons, Interested, explicit choice and refresh recovery |
| 7. API | 1:15 | Both rankings, correct identity, references and coordinates |
| 8. Verification | 1:00 | Current component checks and separate first local synthetic worker run |
| 9. Deployment | 1:15 | Current exact-model local images; cloud revision/TF access pending |
| 10. Monitoring | 1:00 | Actual local container requests; production-log visibility denied |
| 11. Rubric | 1:15 | Requirement/evidence/gap matrix |
| 12. Handoff | 1:15 | Reuse existing cloud work, verify deployment/logs, team review and Canvas |

## Demo setup

Use the [existing-export route](reproduce.md#reuse-the-existing-export-without-retraining). Do not retrain the real team model for a UI demonstration. Run `tools/verify_serving_export.py --artifact-dir /approved/export --out .integration-runtime/fresh-demo --serve` after locked backend setup, then use its printed URL. It supplies five valid favorites per reader. Keep the process running; Ctrl-C stops only its two loopback services.

Open a recommendation and read both reasons. Mark Interested for each reader, choose together, return to the shortlist, then refresh to show the recovered choice. Change one response to Pass to revoke the choice; Start over offers a confirmation. Search accepts Mieville/Miéville. Feedback uses a separate explicit button; do not send a production test vote unintentionally.

The [original public Site](https://tastebridge-prototype.landenini.chatgpt.site/) is a separate static 23-book frontend demonstration, not the model service. Saved actual-model screenshots/logs/JSON support discussion when the local server is unavailable; they do not replace cloud evidence.

## Questions

| Question | Evidence-based answer |
| --- | --- |
| Which model is shown? | Existing team B2 ALS export, 5,000 works, exact fingerprint cb4457b668e3. No new real-data fit ran |
| How is ranking computed? | Unit-normalized mean of favorites, cosine to books, minimum or average of reader scores. Serving math is unchanged |
| What do reasons and lines mean? | Actual reference books/shared shelves; the optional projection is approximate similarity. No new LLM reason path |
| Does the synthetic table establish quality? | It verifies metric output. Historical real-data evaluation and local synthetic runtime evidence retain separate labels |
| Why only 126 pairs in the new worker run? | Requested 300 was capped by eligible combinations from 23 held-out simulated readers: 63 similar / 63 different |
| How does recovery handle a new model? | Saved choice/votes carry the exact model fingerprint; changed bytes clear unverified opinions. IDs recover without saving full metadata or queries |
| Does the worker satisfy cloud tracking/workflow? | Local image and one synthetic invocation passed. Qualifying cloud execution and acceptance of its tracker/workflow approach remain unverified |
| What remains? | Existing job/tracker/workflow/service evidence, current revision/TF access, production logs, native/team slide review and authorized Canvas submission |

[Operator handoff](operator-handoff.md) names the denied read operations and exact next inputs. The official deadline is November 12, 10pm Eastern. No Canvas submission is implied by the branch or deck.
