# Team status

Checked October 12, 2026. Sources: the [MS1 proposal](../milestones/ms1/), Nikhil's October 7 meeting summary (19:48) and full transcript (22:38), and the October 8 and 12 WhatsApp work-split messages. The October 12 TF transcript was also read in full; transcription errors are paraphrased here. Official course requirements take precedence over informal meeting wording.

October 12 update: [Nikhil's backend PR #2](https://github.com/cathyliu0510/TasteBridge/pull/2) establishes his API/deployment workstream. Its SPEC and implementation were checked against the frontend; [results, joint review instructions and open integration choices](backend-integration.md).

Jenny's A now connects to that API; the frontend/backend Docker app stack and browser flow have been checked with toy artifacts. [MS2 app evidence](ms2/frontend-api/) records the completed frontend integration. This does not settle ownership or completion of the data/training pipeline.

## Milestone 2 work split

These are members' own offers, not a finalized allocation of every task.

| Member | Work volunteered | Evidence |
| --- | --- | --- |
| Jenny Zhu | Frontend/user flow and design-choice documentation, starting from the prototype | Oct 8, 11:49 |
| Cathy Liu | Data preprocessing; earlier baseline models, evaluation metrics and results documentation offer remains recorded | Oct 12, 18:20; earlier offer Oct 8, 11:58 |
| Anhad Ahluwalia | Testing and TF presentation slides; offered to help Cathy and suggested a shared Q&A rehearsal | Oct 12, 18:14 and 18:21; earlier offer Oct 8, 14:42 |
| Nikhil Babani | Backend API/deployment; PR #2 implements search, recommendations and anonymous feedback with toy artifacts | PR #2 / SPEC, checked Oct 12; earlier offer Oct 8, 16:29 |
| YiTong Li | DVC setup, description embeddings and a local ChromaDB retrieval example | Oct 12 update, edited 17:26 |

Cathy and YiTong's workstreams are now confirmed by their own messages. Project-wide pipeline integration ownership and the DVC remote still need confirmation. YiTong's proposed file paths are tentative; description embeddings prepare the MS3 hybrid and do not replace the backend's current `item_embeddings.npy` contract. PR #2 includes the backend's Docker/uv setup.

## Confirmed requirements and existing plan

**[MS2: October 20, 10pm ET](https://harvard-iacs.github.io/2026-AC215/milestone2/).** Deliver through the `milestone2` branch and submit its full commit hash on Canvas. Provide containerized ingestion/preprocessing, a trained or adapted baseline, `uv`/`pyproject.toml`, one-command execution, data-version records, run logs and a small input/output artifact, environment evidence, and an app skeleton with basic UI/backend interaction. The proposal chooses DVC for data tracking. The current frontend demo does not establish that the data pipeline, model or backend are complete.

Bring slides for a **15-minute presentation** and be ready to discuss repository files during group and individual Q&A. The TF's comment about simple slides and avoiding a code walkthrough does not remove these requirements. [Course policy](https://harvard-iacs.github.io/2026-AC215/#team-projects) requires every member to understand the whole project.

The proposal's later dates match the current course pages: [MS3 Nov 12](https://harvard-iacs.github.io/2026-AC215/milestone3/), [MS4 Dec 1](https://harvard-iacs.github.io/2026-AC215/milestone4/), and [MS5 Dec 11, showcase Dec 10](https://harvard-iacs.github.io/2026-AC215/milestone5/). All milestone submissions are due at 10pm ET. Exact graded-meeting times remain unconfirmed.

## October 7 meeting follow-up

- Track meaningful contributions under each member's own commits. Non-coding work can be documented in Markdown. Record AI assistance and feature boundaries, and understand the code and design choices.
- Keep the repository organized and runnable. Use Docker and uv for Python components; the TF also emphasized Pulumi for later cloud work, consistent with the [course topics](https://harvard-iacs.github.io/2026-AC215/#course-topics-overview).
- Commit a credential-free `.env.example` when configuration is introduced; exclude `.env` and credentials. Cloud secret-storage details still need to be selected and checked before implementation.
- Regular meetings serve as office hours; milestone evaluations include presentations and individual questions. The TF emphasized testing behavior and explaining choices across the team.

## Data and scope audit

The [UCSD source](https://cseweb.ucsd.edu/~jmcauley/datasets/goodreads.html) confirms the proposal's raw genre counts, public-shelf origin, academic-only use and prohibition on redistribution/commercial use. The two genres overlap. The 5,000-work and 500,000-interaction caps are now applied: the full-data snapshot `gr-317756d1a1ad` retains 5,000 works, 9,896 readers and 499,915 interactions ([pipeline README](ms2/datapipeline/README.md#real-data-run-oct-16-full-files)). Dataset files are linked from the root README rather than committed here.

The meeting discussed book **metadata**, not full-book embeddings. Goodreads contains individual histories; simulated-pair metrics cannot establish real joint acceptance. The 12–20-pair study remains a proposal plan, with no recruitment or results verified.

## Open choices and suggestions

The hybrid architecture remains open: MS1 lists LightFM-style and two-tower approaches; a transformer was mentioned in the meeting without a selection. Sparse/dense retrieval, an agent exploring preferences, LLM metadata enrichment, and reading-account/MCP integration were exploratory suggestions. No replacement architecture or additional product commitment was established.

The two-reader scope, five favorites each, metadata-grounded reasons and a 2D model map remain the MS1 starting point. A 3D map, groups of 3–5, and LLM rephrasing are stretch goals. The standalone prototype uses 23 curated sample books and fixed theme vectors; connected A uses the backend's 52 hand-picked books and toy shelf vectors. Neither mode uses a trained model yet.
