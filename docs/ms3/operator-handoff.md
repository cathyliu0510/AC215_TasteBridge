# MS3 operator handoff

The application source `2a87e20` passes current clean-checkout API/browser and Linux/amd64 container checks against the existing team model. The private preparation branch exists and the original public Site serves frontend `20261105.1`. The [current report](overnight-progress-20261105.md) links exact sources and proof. Google Cloud execution/deployment/monitoring and Canvas remain unverified.

| Remaining item | What is known | Next action |
| --- | --- | --- |
| Existing team work | Pinned GCS export reads succeed; Cloud Run, Vertex jobs/pipelines, registry and production-log reads return 403 | Supply existing job, pipeline, tracker and service/revision links plus sanitized evidence, or arrange appropriate read-only visibility. Check these before creating duplicates |
| Tracked training/workflow | Historical local reproducibility and new local worker preparation/runtime evidence exist | Reuse the team's qualifying run. If none exists, confirm platform, data, service identity, output locations, tracker/workflow equivalence and cloud execution/cost authorization |
| Cloud service | Current exact-model local images pass; invocation settings remain unchanged | Authorized operator verifies existing service state and approved private registry, then publishes matching images if needed. Record revision, image/model hashes and TF access |
| Monitoring | Local request logs and one explicit local smoke-feedback event exist | Capture production request/error/performance events linked to that revision and document approved log access |
| Team presentation/submission | Editable 12-slide/900-second draft now incorporates real-model UI and current local container evidence | Close cloud cells, native PowerPoint/Keynote check, reconcile architecture PR #11, team review, then authorized submitter sends full SHA on Canvas |

The directly denied read permissions were `run.services.get`, `aiplatform.customJobs.list`, `aiplatform.pipelineJobs.list` and `artifactregistry.repositories.get`. The logging error did not identify a precise missing grant. Future deployment policy verification also needs project/repository `getIamPolicy` visibility; those grants have not been tested or changed. Folder/organization inherited policy remains an administrator review item. [Readiness record](evidence/identity-handoff-20261105/cloud-readiness.json).

The recovered export stays in ignored local runtime storage. No real reader histories or real processed tables were downloaded. Historical training metadata and evaluation context are retained with their original source. The rubric does not impose a separate blanket real-data requirement, but requires qualifying execution, tracking and system evidence.

`deploy.py publish` uploads images and updates the existing service while preserving ingress/invocation settings and recording prior traffic for rollback. It requires a reviewed exact-model lock and fresh private-project/registry policy checks. `admin-setup.sh` changes IAM and was not run. No Google Cloud training, deployment or IAM write, new credential, paid job or Canvas submission occurred.

The [original public prototype](https://tastebridge-prototype.landenini.chatgpt.site/) is Site version 7 / frontend `20261105.1`, a separate 23-book static demo. Its established access and ownership were preserved; version 6 is retained for rollback. It is not model deployment evidence.

[Evidence index](evidence/index.json) · `python3 tools/check_ms3.py` · [Official rubric and deadline](https://harvard-iacs.github.io/2026-AC215/milestone3/): **November 12, 10pm Eastern**, with a 15-minute team presentation. The checker validates recorded paths/coverage only. Keynote application-control approval is unrelated to GitHub permission.
