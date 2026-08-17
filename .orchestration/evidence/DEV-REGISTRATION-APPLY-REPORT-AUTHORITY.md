# DEV Registration apply-report authority evidence

Date: 2026-08-18 (Asia/Seoul)

## Baseline

- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Product SHA: `78448566c9cb461bacafa0afc425572d4fefd0ad`
- Deployed OCI revision: `78448566c9cb461bacafa0afc425572d4fefd0ad`
- Authoritative runtime: Node POC at `http://127.0.0.1:39083`
- Web: loopback-published and healthy
- No push, G1/G2 publication, PREP/OPS mutation or destructive migration was performed.

The preceding Product `5e600320e08da16c67dcb4c0e4dce76162230f04` already completed the bounded
READY candidate-to-governed-CR slice. This change did not rewrite preparation, CR approval, provider
apply or Account/Auth.

## Registration contract reconciliation

The read-only audit established the following boundaries from
`docs/adr/0016-durable-typed-bulk-registration-binding.md`,
`docs/adr/0041-accountable-registration-execution-and-evidence.md` and
`docs/30_TYPED_BULK_CATALOG_METADATA_PRD.md`:

- Canonical preparation requires durable receipt/candidate/provenance state, leases and restart
  recovery. The current Node POC keeps preparation in a Web-memory `Map`; MinIO objects and Airflow
  callbacks do not reconstruct that canonical state after restart. Adding storage requires a real
  schema/retention/concurrency decision, so it remains
  `HOLD_REGISTRATION_DURABLE_STORAGE_DECISION`.
- Canonical outbox is persistent command/event evidence, not another label for the browser receipt.
  The Node POC has no canonical outbox. No queue, table or worker was invented.
- Provider apply belongs to the existing governed CR apply lease/attempt/transition contract. The
  Node POC has no apply worker or apply queue, so final lane completion was not relabelled as provider
  apply and no direct DataHub write was added.
- Apply-report is distinct provider-apply evidence, not a projection of CR test-runs. With no apply
  job, the only truthful current result is the canonical `NOT_STARTED` report.
- The exact typed targets remain TABLE_DESCRIPTION → `datasetProperties`, COLUMN_DESCRIPTION →
  `schemaMetadata`, DATASET_DOMAIN → `domains`, DATASET_TERM → `glossaryTerms`, and DATASET_TAG →
  `globalTags`. Existing recognition does not prove the full multi-row/grouping and workspace UUID
  resolution contract, so typed completeness remains partial.

One retained historical `BULK_CATALOG_METADATA` CR remains immutable audit history. It was not
hard-deleted or reused as a new provider-write fixture.

## Product slice

The smallest non-architectural slice moves apply-report authority from browser-local construction
to the Node server:

- `GET /poc-api/change-requests/:id/apply-report` is an exact centrally registered route protected
  by the existing `change.read` capability.
- The server validates a bounded CR identity, reads current server-owned core state, hides an unknown
  CR with 404 and returns the exact `GovernanceApplyReport` schema.
- The truthful response is `state=NOT_STARTED`, `job_id=null`, zero attempts, null error/hash/time
  fields, `reconciled=false`, and empty item/attempt projections.
- A successful response is `private, no-store`. Unsupported methods do not resolve to the GET route.
- Live `pocState` browser mode proxies the server route. The old fixed local value remains only for
  explicitly offline/local fallback mode.
- The read path does not change CR state, create an apply job, synthesize evidence or call a provider.

Exactly 15 central capabilities remain. Admin/data authorization, CR three-lane behavior, Origin,
CSRF, CAS and provider integrity contracts were not changed.

## Source validation

- Focused Node authorization/provider tests: 27/27 PASS.
- Focused live POC client tests: 24/24 PASS.
- Full Node POC suite: 106/106 PASS.
- Full frontend suite: 87 files, 594/594 PASS.
- ESLint and TypeScript: PASS.
- POC production build and general production build: PASS. The existing Vite chunk-size warning
  remains a non-blocking backlog item.
- Compose render, repository static verification and `git diff --check`: PASS.
- The initial system-Python static command lacked PyYAML; the supported repository `.venv` command
  then completed the actual static verification successfully.

## Runtime evidence

The exact Product image was built and Web alone was recreated. An intermediate build/deploy attempt
was rejected because its OCI revision string did not equal the full Git SHA; it contributed no PASS.
The final running image label exactly equals the Product SHA.

A disposable DEV viewer was created by the coordinator only. The password travelled through stdin
to a memory-only bootstrap process; it was never placed in argv, an environment dump, a worker
prompt, evidence or the read-only container filesystem. The runtime results were:

- login: 200
- `/auth/me` before cleanup: 200
- retained CR apply-report: 200 with exact schema and `private, no-store`
- unknown CR: 404
- unsupported POST: 404
- credential disabled and its active session revoked
- `/auth/me` after cleanup: 401

No Table grant, System mapping, provider write or new CR was needed. The password/cookie temporary
files were removed. Final current observations were:

```text
Catalog Tables                         2002
MCL source/checkpoint/ledger/CR-link  2/2/66/4
active Table grants                   0
active sessions                       0
enabled runtime-test credentials      0
feature policy version/cells          24/120
```

The inspection Admin remains active, login-enabled, role admin, maximum grade restricted, failed
attempts 0, unlocked, with no Responsible System and no active session. Its password was not read,
reset or changed.

## Independent validator

A fresh independent Gemini 3.1 Pro High plan-mode validator recorded the authoritative worktree,
branch, clean Product HEAD, exact deployed OCI revision and Node POC authority. It reran the focused
checks and the 106-test Node POC suite, reviewed the non-mutating apply-report boundary, and returned
PASS with no modified files or runtime mutation. Legacy FastAPI was not used as evidence.

## GX, Governance, Chat and documentation boundaries

- GX: source proves `great-expectations==1.19.1` and an isolated compiler/execution seam. The
  version-matched DataHub validation action, token/platform-instance identity and actual
  assertion-emission/GMS receipt are not tracked or runtime-proven. Status remains
  `GX_CANONICAL_RUNTIME_CONTRACT_REQUIRED`; no fake assertion service was added.
- Governance: current active-user read remains. Canonical document mutation roles are not clear
  enough to mutate Product, so `HOLD_GOVERNANCE_DOCUMENT_MUTATION_POLICY` remains.
- Chat: General/Vector/AUTO keep their verified baseline. Graph remains partial/fail-closed for
  non-Admin until stable canonical Table identity/provenance exists before traversal.
- Knowledge and Quality remain `USER_FEATURE_DEFINITION_REQUIRED`; Product code was not expanded.

## AGY usage and discarded claims

- Claude Sonnet 4.6 (Thinking) was requested/effective for the critical mutation but returned an
  explicit Individual quota exhaustion message before commands or changes. Its ownership was fenced.
- One Gemini 3.1 Pro High mutation launch was fenced before commands because process cwd was the
  wrong worktree. Its result was discarded and it changed no file.
- The correctly launched Gemini 3.1 Pro High mutation worker changed six owned files. Coordinator
  review corrected its response-schema, cache-header and fixture defects before validation.
- Registration read-only Worker A completed. Its statement that no durable-storage HOLD existed was
  discarded because the canonical durability requirement plus missing storage decision establishes
  the user-directed `HOLD_REGISTRATION_DURABLE_STORAGE_DECISION`.
- GX/Governance/Chat read-only Worker B stopped making progress and was fenced as
  `HUNG_READ_ONLY_WORKER_NO_PRODUCT_CHANGES`; none of its claims were used.
- The fresh independent Gemini validator passed at the final exact Product/deployed SHA.

## Overengineering check

```text
new tables       0
new dependencies 0
new services     0
new containers   0
new queues       0
new workers      0
new frameworks   0
new capabilities 0
```

`new workers` above means Product runtime workers, not temporary AGY validation agents.

## Canonical status

| Registration stage | Status | Boundary |
|---|---|---|
| Upload / preparation | `COMPLETE_RUNTIME_VERIFIED` | Runtime works; restart durability remains HOLD |
| Airflow processing | `COMPLETE_RUNTIME_VERIFIED` | Existing callback reaches READY |
| Candidate / preview | `COMPLETE_RUNTIME_VERIFIED` | Current scoped candidate and preview |
| Governed CR creation | `COMPLETE_RUNTIME_VERIFIED` | Exact READY candidate, ETag/idempotency/CAS |
| CR approval | `COMPLETE_RUNTIME_VERIFIED` baseline | Existing independent three-lane workflow |
| Actual provider apply | `NOT_STARTED` / `PARTIAL` | No Node POC apply lease/worker/queue |
| Apply result projection | `COMPLETE_RUNTIME_VERIFIED` | Server-authoritative truthful `NOT_STARTED` |
| Restart recovery | `HOLD_REGISTRATION_DURABLE_STORAGE_DECISION` | Canonical durable schema decision required |

Registration overall remains `PARTIAL`. The next smallest Product mutation is not authorized until
the durable receipt/candidate/outbox/apply storage and ownership decision is made. Conflict-free
read-only GX/Governance/Chat/Knowledge/Quality discovery may continue.
