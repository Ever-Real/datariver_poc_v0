# MCL runtime / automatic detection activation evidence

- Date: 2026-08-17, Asia/Seoul
- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Product SHA: `6c67242756ac3ee8fef0cf6d5d8084daaa857fa5`
- Deployed OCI revision: `6c67242756ac3ee8fef0cf6d5d8084daaa857fa5`
- Canonical DEV origin: `http://127.0.0.1:39083`
- Authoritative runtime: Node POC, not legacy FastAPI
- MCL DEV runtime / automatic-detection vertical slice: `COMPLETE_RUNTIME_VERIFIED`
- Scheduler startup / catch-up / restart: `COMPLETE_RUNTIME_VERIFIED`
- Actual KST 00:00 wall-clock observation: `TARGET_RECHECK_REQUIRED`
- PHASE 1D overall: `PARTIAL`

No password, password hash, cookie, session token, provider token, credential value or disposable
asset identity is recorded here.

## Result

The existing MCL source, checkpoint, exact append-only ledger, Change History/Monitoring projection
and optional CR-link ledger were activated against the current DEV DataHub/Kafka source without a
second ledger, checkpoint or event system. The slice preserved historical sources and events while
making operational status depend only on the exactly configured current source.

This is not a synthetic midnight acceptance. Startup catch-up, same-day scheduled receipt,
idempotent replay and same-configuration Web restart are verified; actual passage through KST
00:00 remains a separate target observation.

## Baseline and binding contract

Before activation, the current database contained:

```text
sources / checkpoints / ledger events / CR-link events = 2 / 2 / 46 / 4
current-source checkpoint next_offset / version        = 52942 / 94
Kafka earliest / latest                                = 46325 / 55579
retention gap                                           = none
```

The selected ignored DEV environment already expressed the current provider contract. Runtime
presence checks exposed booleans/counts only and found all 10 required bindings:

```text
POC_CHANGE_HISTORY_SCHEDULER_ENABLED
POC_MCL_KAFKA_BROKERS
POC_MCL_KAFKA_CLIENT_ID
POC_MCL_KAFKA_GROUP_ID
POC_MCL_KAFKA_TOPIC
POC_MCL_SOURCE_IDENTITY_HASH
POC_MCL_SCHEMA_CONTRACT_HASH
POC_MCL_PROVIDER_NAME
POC_MCL_PROVIDER_VERSION
POC_MCL_SCHEMA_REGISTRY_URL
```

Scheduler enabled state is owned by `POC_CHANGE_HISTORY_SCHEDULER_ENABLED=true`; the unrelated
legacy-looking key `POC_MCL_SCHEDULER_ENABLED` is not the runtime contract. Secret values were not
printed or copied into source/evidence.

## Catch-up and deterministic ledger

The first direct catch-up consumed 2,637 source records, appended 15 exact ledger events and moved
the current checkpoint to offset 55,579. An immediate replay consumed and appended zero, proving
idempotency at the same boundary.

A DEV-only disposable DataHub Dataset lifecycle then exercised only event classes already supported
by the current MCL contract:

| Source change | Exact normalized ledger result |
|---|---|
| Baseline description and schema | `DOCUMENTATION CREATE`; `TECHNICAL_SCHEMA` field create |
| Description update and one added column | `DOCUMENTATION UPDATE`; `TECHNICAL_SCHEMA` added field |
| Current status removal | `LIFECYCLE DELETE` |

The final catch-up consumed eight delayed source records, appended no duplicate ledger rows and
advanced the current checkpoint to offset 55,596 at version 2,748. The disposable asset remains a
tombstone/history record; no destructive hard delete or offset reset was performed.

Final invariants:

```text
sources / checkpoints / ledger events / CR-link events = 2 / 2 / 66 / 4
current-source exact match                            = 1
current-source checkpoint next_offset / version       = 55596 / 2748
duplicate exact source positions                      = 0
```

The historical source/checkpoint remains readable. Historical event lists and counts still include
both sources; only the operational capture/sync/ledger-guarantee summary is current-source scoped.

## Scheduler startup, catch-up and restart

Scheduler startup ran the existing MCL capture, reconciled the current 2,002-asset Catalog and
wrote the existing receipt contract:

```text
scope            = change-history-scheduler-v1:datariver:poc:change-history-scheduler:v1
receipt version  = 2
scheduled boundary = 2026-08-16T15:00:00.000Z
completed at       = 2026-08-17T12:34:13.682Z
catalog version    = 39
```

A same-configuration Web restart preserved ledger count 66, checkpoint offset/version 55,596/2,748,
receipt version 2 and Catalog version 39. Web returned healthy on loopback port 39083 after restart.
PostgreSQL, DataHub, Neo4j and unrelated support services were not recreated for this acceptance.

## Current-source operational summary correction

The pre-existing historical source made the operational summary report `SOURCE_AMBIGUOUS` even
though deployment configured one exact current source. Product
`6c67242756ac3ee8fef0cf6d5d8084daaa857fa5` makes the bounded correction in
`frontend/poc-server.mjs` and its tests:

- a syntactically valid `POC_MCL_SOURCE_IDENTITY_HASH` selects exactly one matching current source,
  its checkpoints and its exact ledger rows for operational status;
- the historical event/list/count contract remains unfiltered and readable;
- a valid configured hash with no exact stored source fails closed using the existing
  `SOURCE_NOT_CONFIGURED` status;
- missing or syntactically invalid configuration preserves the earlier multi-source ambiguity
  behavior;
- no new status enum, table, dependency, service or policy framework was introduced.

The deployed image carries the exact Product revision. Runtime `/api/v1/change-history/summary`
returned `CONTIGUOUS_CAPTURE_RECORDED`, one first-MCL-offset and a present ledger guarantee, while
the historical events endpoint returned all 66 events.

## Runtime account hygiene

Secret-bearing runtime acceptance was performed only by the coordinator with an in-memory
cryptorandom disposable Admin credential. The actual Node POC returned login 200, `/auth/me` 200,
summary 200 and events 200. Cleanup then disabled the credential, revoked its active session and
inactivated the disposable profile.

Post-cleanup read-only checks found:

- inspection `admin`: active, login-enabled, role `admin`, maximum grade `restricted`, failed
  attempts 0 and not locked;
- login-enabled credentials 1, active sessions 1 and active Table grants 0;
- no active MCL validator credential, profile or assignment.

The inspection admin credential/session was not reset, revoked or treated as disposable cleanup.

## Tests and regression

| Gate | Result |
|---|---|
| Focused current-source operational summary tests | PASS |
| Node POC full suite | PASS — 102/102 |
| Frontend full suite | PASS — 87 files, 592/592 |
| Lint | PASS |
| Typecheck | PASS |
| POC production build | PASS |
| Frontend production build | PASS; existing Vite chunk advisory only |
| Compose no-interpolate render | PASS |
| Secret/hardcoding diff scan | PASS |
| `git diff --check` | PASS |
| Exact Product image build/deploy/health | PASS |

The first full Node invocation inherited the live ignored DEV environment and produced two fixture
scope 502/503 failures. This was an invocation-isolation defect, not a Product regression. The
canonical isolated invocation
`POC_ENV_FILE=poc-server.test.env.missing npm run test:poc-server` passed 102/102 on the final source.

Existing login/session, inspection admin, User↔Table grant, feature policy, System mapping, CR
three-lane workflow, Change History, MCL ledger/checkpoint/CR-link, Catalog/Search/Tree,
Monitoring/Governance, provider binding, exact Airflow service route and loopback network contracts
remained intact.

## DEV support-service read-only audit

The parallel read-only audit is recorded here as the gate into the next product priority, not as a
support-service Product completion:

| Service | Current DEV observation | Canonical status |
|---|---|---|
| Airflow | 3.3.0 image/container healthy on loopback 18888; three Registration DAGs mounted; current Web Airflow URL/service credentials absent | `PARTIAL` |
| MinIO | Existing 2025-09-07 image healthy on loopback 9000/9001; five buckets; container owned by another workspace Compose; authoritative Web bindings absent | `PARTIAL` |
| GX | No running/stopped GX container and no proven current runtime contract; source compiler/worker seams exist, but no checkpoint→result→DataHub assertion E2E | `BLOCKED` / `UNKNOWN_CONTRACT` |

No Airflow, MinIO or GX Product/runtime mutation was started. PREP/OPS were not inspected as
authority or changed.

## AGY usage

| Role | Requested model | Effective model | Result |
|---|---|---|---|
| MCL/source and support-service audits | Gemini 3.1 Pro High | Gemini 3.1 Pro High | Read-only findings; no Product/runtime mutation |
| Critical current-source correction | Claude Sonnet 4.6 (Thinking) | Claude Sonnet 4.6 (Thinking) | Two-file bounded implementation; coordinator reviewed and minimally repaired before all final gates |
| First fresh validator | Gemini 3.1 Pro High | Gemini 3.1 Pro High | Discarded after an unauthorized secret-bearing environment-read attempt; no Product/DB/runtime mutation |
| Fresh independent validator retry | Gemini 3.1 Pro High | Gemini 3.1 Pro High | Accepted read-only Node POC validation; exact Product/OCI, focused tests, binding booleans and database invariants confirmed |

Claude did not report quota exhaustion, so no model fallback was used for the critical mutation.
Secret-bearing runtime creation, login and cleanup remained coordinator-owned.

## Independent validator

Fresh retry task `task_e934bd15a3e1`, dispatch `ctx_6c391441e60a`, recorded the authoritative
worktree, branch, Product HEAD, matching deployed OCI revision and effective Gemini 3.1 Pro High.
It used the Node POC runtime only and modified no Product files or runtime state.

It independently confirmed:

- focused current-source summary tests pass;
- loopback health and OCI revision are exact;
- all 10 required MCL bindings are present and scheduler is true without exposing values;
- source/checkpoint/ledger/CR-link counts are 2/2/66/4;
- the configured source matches exactly once, checkpoint offset is 55,596 and duplicate exact
  source positions are zero;
- actual KST midnight remains `TARGET_RECHECK_REQUIRED`.

## Overengineering check

```text
new tables            = 0
new dependencies      = 0
new services          = 0
new containers        = 0
new provider versions = 0
new frameworks        = 0
new capabilities      = 0
```

## Product SHA and Evidence SHA

- Product SHA: `6c67242756ac3ee8fef0cf6d5d8084daaa857fa5`
- Deployed OCI revision: `6c67242756ac3ee8fef0cf6d5d8084daaa857fa5`
- Evidence SHA: the separate documentation commit containing this file, `CURRENT.md` and the master
  backlog. It is intentionally not folded into the Product revision.

## Canonical status and remaining risks

| Surface | Canonical status |
|---|---|
| MCL current source binding and direct catch-up | `COMPLETE_RUNTIME_VERIFIED` |
| Exact append-only ledger and replay idempotency | `COMPLETE_RUNTIME_VERIFIED` |
| Schema/description/lifecycle automatic detection | `COMPLETE_RUNTIME_VERIFIED` for the supported event contract |
| Change History/Monitoring current-source operational summary | `COMPLETE_RUNTIME_VERIFIED` |
| Scheduler startup, same-day catch-up and same-config restart | `COMPLETE_RUNTIME_VERIFIED` |
| Actual KST 00:00 wall-clock execution | `TARGET_RECHECK_REQUIRED` |
| Airflow DEV feature-support gate | `PARTIAL` |
| MinIO DEV feature-support gate | `PARTIAL` |
| GX checkpoint→result→DataHub assertion | `BLOCKED` / `UNKNOWN_CONTRACT` |
| PHASE 1D overall | `PARTIAL` |

CR linkage remains an exact four-event historical ledger; this slice did not fabricate a new CR
candidate or rewrite history. Supporting-service ownership/bindings and GX's exact existing
PREP/OPS-derived contract remain the next gate. No Registration, Governance, Chat refinement,
Knowledge, Quality, PHASE 1E/1F or migration Product mutation was started.

## Next smallest slice

Complete the DEV feature-support gate without coupling every service to base Compose:

1. bind the existing owned Airflow and MinIO contracts only where Registration currently consumes
   them;
2. resolve the canonical GX version/image/runtime contract from current repository and approved
   environment evidence;
3. require actual GX checkpoint→result→DataHub assertion E2E before claiming GX readiness;
4. keep actual KST midnight as a separate MCL target observation.
