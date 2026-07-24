# Phase 5 durable Knowledge source jobs — PRD and execution checklist

## Objective

Replace the synchronous PDF-to-DRAFT path with a bounded, durable and recoverable job. Submission
pins the exact source, graph base, ontology and model configuration. A worker may call fallible
object-storage and inference providers only after a fenced claim, and may persist a proposal only
when one final transaction proves every pinned security and content binding is still current.

This Phase produces a typed `DRAFT` changeset only. It never submits, reviews, publishes, activates
or projects a release.

## Scope

Included:

- dedicated `knowledge.source_analysis_jobs`, attempt and event ledgers with forced workspace RLS;
- a least-privilege `datariver_knowledge` worker principal and separate database/object credentials;
- idempotent `202 Accepted` submission plus owner-authorized status, bounded list and
  version-fenced cancellation APIs;
- active-first owner history with an opaque cursor, at most 100 rendered rows and a transactional
  maximum of 20 non-terminal jobs per owner/graph so no active job falls behind terminal history;
- immutable source, explicit empty-base or exact active-release, graph version, ontology
  ID/checksum, parser contract and activated model-binding pins;
- database-clock lease, random token hash, epoch and attempt fencing;
- bounded retry, cancellation, expired-lease recovery and late-worker rejection;
- final in-transaction requester reauthorization and exact source/base/ontology/config revalidation;
- the same fail-closed authorization/source/configuration preflight before source read and every
  provider egress batch, so revoked authority cannot leak content to inference before finalization;
- all-or-none pages, embeddings, extraction evidence, typed operations, DRAFT changeset, job state,
  attempt state, audit event and outbox persistence;
- opaque evidence locators instead of private object-store keys in changesets, API responses and UI;
- hidden-tab-aware bounded UI polling, resume, cancel and result-to-changeset navigation;
- current-source unit, actual-PostgreSQL concurrency/RLS/migration, frontend and static gates.

Excluded:

- automatic changeset submit/review/publish/activate/projection;
- Mode A ontology generation and database/dynamic one-pass source ingestion;
- general Chat `GENERAL`/`VECTOR`/`GRAPH`/`AUTO` routing;
- runtime reranking, Neo4j projection workers, catalog API or MCP;
- target WSL/private-provider/human-browser/load claims without target evidence.

## Product, data and security requirements

| ID | Requirement | Acceptance |
|---|---|---|
| K-JOB-01 | Reject ineligible work before durable submission | ownership, accepted PDF integrity, size, PUBLIC/INTERNAL inference classification, governed base, active ontology and activated model contracts are checked before a job exists |
| K-JOB-02 | Pin the preparation snapshot | the job stores source identity/version/hash, graph version, explicit base state, ontology ID/hash, parser hash and secret-free model binding documents/hashes |
| K-JOB-03 | Make submission idempotent and actor-bound | the same actor/key/request returns one job; changed payload, actor, graph or upload conflicts |
| K-JOB-04 | Isolate worker authority | API can submit/read/cancel but cannot claim or complete; the worker uses a NOBYPASSRLS principal with column-scoped grants |
| K-JOB-05 | Fence every attempt | claim uses DB time, `FOR UPDATE SKIP LOCKED`, random token hash and monotonically increasing epoch; renew/finalize/fail require the current non-expired token, epoch, owner and attempt |
| K-JOB-06 | Bound retries and recovery | only classified transient dependency failures retry with capped backoff; expired attempts become `SUPERSEDED`; maximum attempts end in `FAILED` |
| K-JOB-07 | Linearize cancellation | queued work cancels immediately; running work becomes `CANCEL_REQUESTED`; final persistence checks cancellation and cannot race a successful cancel |
| K-JOB-08 | Reauthorize before egress and at the write boundary | current subject and membership, `kg.edit`, clearance, graph/source envelope and access expiry are rechecked before source/provider egress and again while the final rows are locked |
| K-JOB-09 | Reject drift atomically | changed source, active base, graph version, ontology/hash or activated configuration yields `STALE` with zero pages, operations, extraction run or changeset |
| K-JOB-10 | Keep canonical persistence atomic | pages, embeddings, extraction run, DRAFT, operations, source/job/attempt state, audit event and outbox commit together or not at all |
| K-JOB-11 | Bind complete result evidence | the result hash covers pinned base/ontology/parser/model bindings, every page hash and sorted full typed operation documents including endpoints, classification, provenance and confidence |
| K-JOB-12 | Bound memory and provider calls | 50 MiB/500 pages/40,000 characters per provider page and batch limits remain hard gates; work is in a separate constrained container and the browser renders at most 100 job rows and never source bytes |
| K-JOB-13 | Prevent storage topology disclosure | durable provenance uses `knowledge-source:<snapshot-id>#page=<n>` and content hash, never bucket, private key, endpoint or credentials |
| K-JOB-14 | Keep UI eligibility truthful | CONFIDENTIAL/RESTRICTED graphs do not offer executable source analysis; UI and API explain the PUBLIC/INTERNAL limit without silently lowering classification |
| K-JOB-15 | Preserve honest portability evidence | native and `linux/amd64` compose render are config evidence only; WSL and private-provider execution remain external gates |

## API contract

| Method/path | Result | Notes |
|---|---|---|
| `POST /knowledge/graphs/{graph_id}/sources/{upload_id}/analyze` | `202` job | requires `Idempotency-Key`; compatibility path queues and never performs inference in the request |
| `GET /knowledge/graphs/{graph_id}/source-analysis-jobs?cursor=&limit=` | bounded page | owner-visible, active-first, maximum 100 rows; cursor binds owner/workspace/graph/order and at most 20 active jobs may exist per owner/graph |
| `GET /knowledge/graphs/{graph_id}/source-analysis-jobs/{job_id}` | job | returns state, bounded progress, error code and result only after success |
| `POST /knowledge/graphs/{graph_id}/source-analysis-jobs/{job_id}/cancel` | job | requires `If-Match` and `Idempotency-Key`; terminal success is immutable |

Terminal states are `SUCCEEDED`, `FAILED`, `STALE` and `CANCELLED`. `QUEUED`, `RUNNING`,
`RETRY_WAIT` and `CANCEL_REQUESTED` are non-terminal. Provider error bodies, secret references,
bucket names and object keys are never returned.

## TDD and negative-case checklist

The checked wording below is deliberately limited to the evidence that was actually executed. It
does not turn a source/unit proof into a target-provider, browser or load claim.

- [x] Source tests reject invalid media, size/hash, classification and graph envelope; the isolated
  PostgreSQL oversize case proves zero durable job/event evidence. Enqueue successfully pins the
  tested base, ontology and model revisions; no exhaustive negative no-row matrix is claimed.
- [x] Race identical submissions and prove one actor-bound job; reject key reuse with changed
  title, upload, graph or actor.
- [x] Claim concurrently and prove one current token/epoch/attempt; reject stale/wrong claim
  evidence and recover one expired attempt as `SUPERSEDED`.
- [x] Exercise bounded retry classification and the first expired-attempt recovery in
  worker/PostgreSQL tests; exercise queued and running cancellation plus the cancel/finalize race in
  source and PostgreSQL tests. A maximum-attempt exhaustion matrix is not claimed.
- [x] Revoke the requester after claim and prove the pre-egress worker check and final locked
  reauthorization leave zero proposal rows.
- [x] Change source manifest, graph version, base release, ontology, model binding and classification
  independently in isolated PostgreSQL; every tested drift becomes `STALE`.
- [x] Inject a finalization failure at the extraction-run write boundary and prove the enclosing
  pages/embeddings/run/changeset/operations/job/outbox/audit transaction rolls back.
- [x] Prove the result hash changes for typed property, edge endpoint and pinned-configuration
  changes; the hash contract includes the remaining typed fields and is reviewed in the domain test.
- [x] Prove the created DRAFT stores only an opaque source locator. Job API schemas and UI flow
  expose no bucket, object key, provider endpoint or credential; they do not expose a locator.
  Release/GraphRAG propagation is not claimed by this DRAFT-only Phase.
- [x] Enforce PDF/page/provider-batch/vector/operation limits and keep source bytes out of browser
  job state.
- [x] Prove no-context, wrong-workspace and wrong/expired-claim reads fail under FORCE RLS; prove the
  worker can see only the exact job/source/graph/ontology/requester/model revisions in its live claim.
- [x] Upgrade `0053 -> 0054`, reject unsafe role membership, regenerate canonical `0001`
  deterministically and install `0001 -> 0054` into a completely empty database.
- [x] Pause polling while hidden, cap the polling window, resume by job ID and expose explicit
  cancel/result states without fabricating progress.
- [x] Disable CONFIDENTIAL/RESTRICTED execution with an exact reason and run a synthetic INTERNAL
  PDF-to-DRAFT journey.
- [x] Run whole backend/frontend/static gates, native and `linux/amd64` Compose rendering, and
  independent Application/UI/portability, DB/security and PM traceability reviews.

## Documentation corrections included in this Phase

- [x] Mark the direct `POST /knowledge/graphs/{graph_id}/releases` route as retired (`410`) in the
  API specification; governed changeset publication is the only release creation path.
- [x] Replace stale “typed extraction API absent” statements in the enterprise UI PRD/checklist
  with the durable job contract and its remaining Mode A/database-source exclusions.
- [x] Update the canonical data model, feature/API/test/deployment documents, README and master
  backlog with exact implemented behavior and evidence.

## Executed local evidence — 2026-07-24

- Whole backend gate: Ruff format/lint, strict mypy over 370 source/test files and static
  verification passed; pytest reported `1,369 passed, 84 skipped`. Skips remain explicitly
  environment-gated and are not counted as passes.
- Whole frontend gate: TypeScript, zero-warning ESLint, `45` files / `243` Vitest tests and the
  production Vite build passed. The job history renders one server page of at most 100 rows,
  follows opaque cursors and can restart the same non-terminal poll after its 120-attempt window.
- PostgreSQL 17 isolated gate: additive `0053 -> 0054` and completely empty generated
  `0001 -> 0054` databases each passed all `24` durable-job
  role/concurrency/RLS/recovery/evidence-forgery tests. `alembic check` reported no upgrade
  operations.
- Dirty-role negative probes: an existing direct `DELETE` grant on `knowledge.source_pages` was
  removed by the `0053 -> 0054` re-entry; a temporary role membership allowing `SET ROLE` caused
  canonical migration to fail with the intended error and was then removed. Direct API/worker
  event, outbox and policy evidence forgery failed; upload/governance could not occupy the Knowledge
  evidence namespace, while relay could update only outbox delivery state.
- Canonical `0001` regenerated byte-identically across consecutive runs at SHA-256
  `a9978344ab90982c6d5f6c8929b8a976f34418d5fbcae2a8de6758171bda6f98`.
- Native and `DOCKER_DEFAULT_PLATFORM=linux/amd64` core/object-storage Compose rendering passed.
  This is configuration evidence, not a target runtime or image-execution claim.
- Independent final Application/UI/portability and DB/security reviews reported `P0=0`, `P1=0`.
  The PM traceability review's three P1 findings were closed by narrowing this checklist to executed
  evidence, recording the final audit and synchronizing the phase-control documents.

## Accepted residual P2 hardening

| Item | Owner / backlog | Consequence and disposition |
|---|---|---|
| Remaining negative matrices | SW Quality / `R5-TEST-01` | Add exhaustive ownership/integrity/base/ontology/model no-row enqueue cases and maximum-attempt exhaustion. No broader test claim is made at this Phase boundary. |
| PostgreSQL transaction identity | Data/Security / `R5-DATA-04` | The current same-transaction fence compares row `xmin` with the current XID. Add XID-wrap-aware strengthening. |
| Per-claim runtime configuration pool | Data/SRE / `R5-DATA-02` | A one-connection pool is created for each claim. Correctness is bounded, but low-spec connection churn must be removed or budgeted. |
| Provider-call authorization window | Security/Application / `R5-SEC-07` | Reauthorization occurs immediately before each bounded call and again before persistence, but a narrow call-time TOCTOU remains; measure target revocation timing. |
| Migration re-entry integrity | Platform DB / `R5-DEP-06` | Re-entry verifies required object names, grants and policies; add controlled function-body/owner fingerprints. |
| Object-store IAM | SRE/Security / `R5-DEP-05` + external gate | Database visibility is exact-claim scoped and the worker prefix is restricted, but per-job object IAM is not claimed. Validate the target MinIO/S3 policy below. |
| Shared outbox checks | Data/Application / `R5-DATA-05` | Knowledge rows are producer-fenced and relay-immutable except delivery fields; add generic positive `schema_version`/`attempts` checks after auditing every producer. |

## Local exit gate

The Phase closes only when all in-scope checklist items pass, the schema/model/migration/data-model
documents agree, the deterministic migration check is clean, and independent final reviews report
no P0/P1 issue. A P2 may be carried only with an explicit owner, consequence and next Phase.

## External gates

- [ ] Execute exact-source `linux/amd64` images and revision `0054` migration/recovery on the target
  WSL host.
- [ ] Exercise the private object store and OpenAI-compatible Chat/Embedding endpoints with
  production-like DNS/TLS/credentials/timeouts and restart during inference.
- [ ] Complete distinct-human Admin/Data Steward browser acceptance with the real IdP.
- [ ] Run representative large-PDF queue, worker-kill, retry, load/soak and resource telemetry on
  the target hardware.
