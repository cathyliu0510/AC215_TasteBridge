# MS3 team audit — November 5, 2026

The current frontend `20261104.6` works with the team's existing **5,000-book B2 model**, retrieved from the repository's pinned DVC snapshot. Both ranking modes, the API/relay contract, desktop recommendations, 320px book connections and shared-choice/return interactions passed. This reuses the October model; it is not a new training run, quality evaluation or deployed service.

## Repository and upload boundary

[Repository access evidence](evidence/team-serving-20261105/github-audience.json) confirms `cathyliu0510/AC215_TasteBridge` is **private** and the existing signed-in GitHub account has push permission. [Before-upload remote references](evidence/team-serving-20261105/remote-refs-before.json) show `main` and `milestone2` at `fccfbac53a96de18b71ca1c3f668a6bea115e51e`, no `milestone3`, and the unchanged architecture branch. [PR #11](https://github.com/cathyliu0510/AC215_TasteBridge/pull/11) remains open at `744dc878c4c20e0883f8207adc3d53f78984a67a`; it is not merged by this work.

The requested GitHub action is to create a **preparation** `milestone3` branch in this same private repository, using its existing SSH destination and authentication. The upload includes source, documentation, synthetic aggregate evidence, selected UI screenshots and the review deck. Actual model exports, raw datasets, reader histories, runtime files and credentials stay out of Git. The local draft deck's screenshot-description paths were removed without changing slide visuals. Upload scanning also covers newly introduced historical blobs; historical local paths are non-secret provenance, not credentials. The actual upload result must be verified separately; a prepared branch does not establish a completed milestone or Canvas submission.

The prior Keynote application-control card does not govern GitHub. Any earlier GitHub safety denial must be handled through the original review using the exact verified audience and upload contents. No alternate account, destination, main overwrite or sharing change is authorized by this audit.

## Existing team artifacts recovered

[Retrieval ledger](evidence/team-serving-20261105/team-model-retrieval.json) records the four files and their hashes. Source is the existing `gs://tastebridge-dvc` DVC object index `d084e50dc63c3203fc81d7ba09128074.dir`, pinned by `data/artifacts.dvc`. Each downloaded current-export MD5 matches the index; SHA256 is also recorded.

- Model `b2-als-gr-317756d1a1ad`, data `gr-317756d1a1ad`, created October 20.
- Metadata records 5,000 books, 499,915 interactions and 9,896 users. These are recorded team-artifact counts, not a new measurement of model quality.
- Only `books.json`, `item_embeddings.npy`, `coords_2d.npy` and `meta.json` were retrieved, into ignored runtime storage. No reader history or raw dataset was fetched.
- [Actual HTTP contract](evidence/team-serving-20261105/api-check.json), [source/export hashes](evidence/team-serving-20261105/run.json), [browser checks](evidence/team-serving-20261105/browser-checks.json), [desktop](evidence/team-serving-20261105/team-model-desktop.png) and [mobile](evidence/team-serving-20261105/team-model-connections-320.png) document current integration. No `/feedback` event was sent.

The generic verifier deliberately labels a supplied non-synthetic export `operator_supplied_unverified_provenance`. It does not inspect training provenance; the separate DVC retrieval ledger establishes which existing team export was read. Neither record proves new cloud training or accepted model quality.

## Cloud visibility and remaining work

Existing application-default credentials allow GCS reads. [Read-only metadata checks](evidence/team-serving-20261105/cloud-visibility.json) return IAM **403** for:

| Target | Missing read permission | Consequence |
| --- | --- | --- |
| Cloud Run `tastebridge-staging`, project `tastebridge-511403`, `us-central1` | `run.services.get` | Existing service/revision/access cannot be inspected |
| Vertex custom jobs | `aiplatform.customJobs.list` | Existing training runs cannot be listed |
| Vertex pipeline jobs | `aiplatform.pipelineJobs.list` | Existing workflow runs cannot be listed |

This is not evidence that the team has no jobs or service. Accessible GitHub/Drive material contains historical MS2 work; it does not establish current unpushed/cloud work. Do not duplicate jobs or overwrite cloud state to compensate for missing visibility. No cloud mutation, paid execution, new credential, IAM change or deployment was performed.

Next obtain the existing service/job/workflow/tracker links and sanitized evidence from the responsible teammate, or appropriate read-only project visibility. Verify/reuse that work first. If gaps remain, confirm the team's selected workflow/tracker, execution identity, artifact locations and execution authorization; adapt the existing B2 pipeline. Use a working Docker/gcloud environment for current image validation and an authorized operator for any Cloud Run update. Preserve existing invocation access; obtain actual revision/API/logging evidence and approved teaching-staff access.

The [official rubric](https://harvard-iacs.github.io/2026-AC215/milestone3/) requires a reproducible tracked serverless run, an automated workflow, deployment, a documented/tested API and production monitoring. It does not state a separate blanket real-data mandate. Local synthetic reproducibility and the recovered historical model are useful components, but neither proves the required cloud system. The 12-slide deck remains a review draft with cloud evidence and native rendering still pending. Deadline: **November 12, 10pm Eastern**, full `milestone3` commit hash on Canvas, plus a 15-minute team presentation.

## Verification and completion limits

The existing 82 frontend tests passed for this release, and all **27 current tool/configuration tests pass**. The new 5,000-book HTTP/browser checks passed without changes to model scoring or artifact files. Screenshots contain catalogue/demo content. The local preview processes were stopped after verification. Docker's configured socket and `gcloud` remain unavailable; local Python/Node checks do not substitute for image or live-service checks.

`python3 tools/check_ms3.py` still reports incomplete cloud/submission evidence. It checks manifest coverage and file presence only. The separate public [original Site](https://tastebridge-prototype.landenini.chatgpt.site/) remains a 23-book static frontend demonstration at the same release, with public access unchanged. It is not the model API deployment.
