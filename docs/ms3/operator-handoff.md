# MS3 operator handoff

The latest [team audit](team-audit-20261105.md) verifies the private GitHub repository, existing team DVC export and actual model-to-frontend serving. This is a preparation deliverable; cloud execution and final submission remain incomplete.

| Remaining gate | Verified state | Exact next action |
| --- | --- | --- |
| Existing cloud work | GCS reads succeed. Cloud Run service GET and Vertex job lists return IAM 403 | Obtain existing service/job/workflow/tracker links and sanitized evidence from the team, or appropriate read-only visibility. Check before duplicating work |
| Tracked serverless training and workflow | Local synthetic runs reproduce; the October team model is retrievable | Verify any existing accepted cloud run/workflow. If absent, confirm the team platform, execution identity, locations and execution authorization before adapting/running the existing pipeline |
| Deployment | Current frontend works locally with team B2 model `b2-als-gr-317756d1a1ad` | Use a working Docker/gcloud operator environment to build and smoke the exact images; authorized operator updates existing `tastebridge-staging` and records revision/digests/access |
| Monitoring | Local request logs exist; production log visibility is unverified | Capture a request/error/performance event tied to the live revision and document approved log access |
| Team review and submission | PR #11 remains open; requested MS3 preparation upload is separately tracked | Review integrated code, reconcile architecture work, close evidence gaps and verify final slides; authorized submitter sends the full milestone3 SHA to Canvas |

The four-file model was recovered from the existing pinned DVC snapshot and its hashes checked. It is kept under ignored `.integration-runtime`, outside Git. No raw reader histories were downloaded. Real processed input tables remain absent, but the course does not impose a separate blanket requirement to use real rather than synthetic data; it requires a running, tracked, reproducible cloud system and evidence. The recovered historical model alone does not establish a new cloud training run.

`deploy.py publish` uploads images and updates the existing service while preserving IAM, ingress and access annotations. `--authenticated` verifies an already authorized identity without adding access. `admin-setup.sh` changes IAM and was not executed. No cloud mutation, new credential, sharing change, paid job or Canvas submission was performed.

The Keynote application-control card is unrelated to GitHub. Existing GitHub CLI/SSH authentication has write permission on the private team repo. Prior upload safety review must be handled with verified contents/audience through the original method; no alternative account or destination is a workaround.

The public [TasteBridge prototype](https://tastebridge-prototype.landenini.chatgpt.site/) remains frontend `20261104.6`, a separate 23-book static UX demonstration with unchanged public access. It is not the deployed model API.

Finish the [evidence index](evidence/index.json), run `python3 tools/check_ms3.py`, replace pending cloud slides and complete a native slide check. [Official deadline](https://harvard-iacs.github.io/2026-AC215/milestone3/): **November 12, 10pm Eastern**, with a 15-minute team presentation. The checker verifies paths/coverage only, not authenticity or Canvas status.

Latest independent continuation: [exact artifact identity, deployment/evidence sequence and read-access gaps](deployment-evidence-handoff-20261105.md), with [presentation integration manuscript](presentation-integration-20261105.md). GitHub push remains paused.
