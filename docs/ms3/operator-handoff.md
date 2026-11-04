# MS3 handoff

The local deliverable is reviewable: two reproducible trained-synthetic runs, actual model-to-UI integration, source/input/output hashes, tests, selected evidence and a 12-slide review deck. It is **not** a completed MS3 submission.

## Required work and inputs

| Gate | Input/access needed | Action | Evidence that closes it |
| --- | --- | --- | --- |
| Real input and export | Existing approved `data/processed` directory or team-authorized DVC retrieval; no files are present in either inspected checkout | Verify source/version and run the reproducible path with approved B2 parameters | Input manifest and hashes, export identity, actual API checks |
| Tracked serverless training | Team/TF decision on tracker and Vertex or equivalent, approved project/service account, data/output locations and execution authorization | Implement/adapt and execute the approved cloud training path; record source, parameters, artifacts and metrics | Successful cloud execution ID/configuration, tracking record and screenshot |
| Automated ML workflow | Selected Vertex pipeline or documented equivalent and required service permissions | Implement/adapt orchestration and run it on the approved data; the local runner is the tested component sequence | Successful workflow execution plus reproducible configuration |
| Model/API deployment | Real export, working Docker daemon, `gcloud`, approved image registry/service access and a confirmed staff/public access policy | Use `deploy/cloud-run/` to build and smoke-test current images, then perform the authorized deployment | Actual HTTPS endpoint, image digests/revision/configuration, responding request screenshot |
| Production monitoring | Deployed revision and approved log-reader access | Verify request/error or feedback logging and document access/retention | Real production log event and access instructions |
| Submission | Team review, integration with architecture PR #11, and resolution of the push denial | Authorized maintainer updates remote `milestone3` and submits its full hash on Canvas | Remote branch/full SHA and confirmed submission; final slides with real cloud evidence |

The current environment lacks the Colima Docker socket, `gcloud`, and actual licensed processed tables/model export. This task did not test existing cloud credentials or create new ones. The exact location of any other local approved export remains a pending clarification.

The existing `publish` command uploads images, updates a service and grants public invocation. `admin-setup.sh` changes IAM. These are separate operator actions. The course permits teaching-staff access; confirm the access arrangement rather than assuming allUsers is required.

## Review boundaries

- Keep the existing B2 scoring/export implementation and team work. Local smoke parameters are smaller than the tuned MS2 model and imply no model selection decision.
- Reconcile PR #11 through normal review. Do not merge or overwrite it as part of publishing this work.
- The parent task reports that security review denied GitHub branch pushing. No push was attempted in this continuation, and no alternate account, branch, API or remote is a workaround. The parent did not provide a more detailed rejection reason. Publishing requires resolution through the original approval path.
- The ChatGPT Site remains the earlier static UI review with unchanged sharing. It is not the required model deployment and was not republished here.

## Final review sequence

1. Inspect the exact branch diff and [saved evidence](evidence/local-integration-20261104/).
2. Close the cloud and real-data gates above, updating [evidence/index.json](evidence/index.json) with real proof.
3. Run `python3 tools/check_ms3.py`; its path/coverage check must pass, and a human must still verify screenshot contents and live access.
4. Replace the deck's pending cloud evidence, check native presentation rendering and rehearse the [15-minute plan](rehearsal.md).
5. Submit the reviewed full commit by **November 12, 10pm ET**. [Official instructions](https://harvard-iacs.github.io/2026-AC215/milestone3/).
