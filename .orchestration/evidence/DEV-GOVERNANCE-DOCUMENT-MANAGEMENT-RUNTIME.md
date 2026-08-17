# DEV Governance 정책·표준 문서 관리 Runtime Evidence

Date: 2026-08-18 KST

## Lineage and authority

- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Previous Product/Evidence baseline:
  `78448566c9cb461bacafa0afc425572d4fefd0ad` /
  `185d311a32d6109f9d12f201374c60a3e1dc320d`
- Governance Product:
  `fd379567a220f1e677deb5225b8e0b36c1d28d8d`
- Deployed OCI revision:
  `fd379567a220f1e677deb5225b8e0b36c1d28d8d`
- Authoritative runtime: Node POC at `http://127.0.0.1:39083`
- Push, G1/G2 publication, PREP/OPS mutation and G3/G4 were not performed.

## Closed product slice

The approved policy/standard document management boundary is now enforced without adding a new
role, capability, ACL or workflow:

| Operation | viewer | developer | data_steward | manager | admin |
|---|---:|---:|---:|---:|---:|
| Read | allow | allow | allow | allow | allow |
| Create DRAFT document | deny | deny | allow | allow | allow |
| Append DRAFT version | deny | deny | allow | allow | allow |
| Archive | deny | deny | allow | allow | allow |

The implementation reuses `change.manage` only for Governance document/version create, edit and
archive. A Data Steward does not receive `knowledge.manage` or `knowledge.review`, so this slice
does not widen Knowledge Studio, attachment, submission, review or publication authority.

The server-owned core CAS rejects a non-reviewer attempting to:

- hard-delete a Governance document or version instead of archiving it;
- create a non-DRAFT document/version;
- change document review/publication state or published-version pointers;
- change review/submission/publication fields;
- mutate a previously published immutable version.

Manager/Admin existing `knowledge.review` behavior remains unchanged. Responsible System and Table
ACL are not applied to these unbound policy/standard documents.

Changed Product files:

- `frontend/poc-authorization.mjs`
- `frontend/poc-authorization.test.mjs`
- `frontend/src/poc/pocApi.ts`
- `frontend/src/poc/pocApi.live.test.ts`

## Source and test evidence

| Gate | Result |
|---|---|
| Focused server authorization | PASS — 7/7 |
| Focused POC adapter | PASS — 25/25 |
| Node POC full suite | PASS — 107/107 |
| Frontend full suite | PASS — 87 files, 595/595 |
| ESLint | PASS |
| TypeScript | PASS |
| Production build | PASS |
| Compose no-interpolate render | PASS |
| Secret/hardcoding scan | PASS |
| `git diff --check` | PASS |

The known Vite chunk-size warning remains a technical backlog item; it is not a new regression.

## Independent validator

A fresh read-only Gemini 3.1 Pro High validator recorded the authoritative worktree, branch,
Product SHA, deployed OCI revision and Node POC runtime authority before evaluating the slice. It
confirmed exact Product/OCI equality at
`fd379567a220f1e677deb5225b8e0b36c1d28d8d`, reviewed the bounded Governance contracts and made no
file, Git, database, runtime, container, account, credential or session mutation.

| Validator gate | Result |
|---|---|
| Focused Governance authorization | PASS — 7/7 |
| Focused live POC adapter | PASS — 25/25 |
| Node POC full suite | PASS — 107/107 |
| Frontend full suite | PASS — 87 files, 595/595 |
| Files modified by validator | 0 |

The validator did not inspect a Docker environment or any secret-bearing state. The OCI revision
was read only from the exact `org.opencontainers.image.revision` label.

## Exact build and deployment

`FULL_PRODUCT_SHA` was produced only by `git rev-parse HEAD`, checked as 40 lowercase hexadecimal
characters and passed as the exact `POC_SOURCE_COMMIT` build input. The first post-build query used
`docker compose images -q web`; because the still-running old container referenced the replaced old
image, that query returned a stale/nonexistent image ID. It contributed no deployment or runtime
PASS.

The coordinator then read the just-built `datariver-poc:local` image label directly, proved exact
equality with the full Product SHA, recreated Web only, and proved the running container label again.
The runbook now resolves the built image reference from Compose configuration instead of a running
container image ID. Web health is `ok` at loopback port 39083.

## Runtime acceptance and cleanup

A coordinator-owned memory-only harness generated five cryptorandom disposable credentials. No
password, cookie, token, username, subject ID or document ID was written to evidence, a worker
prompt, argv, environment output or a file.

The exact deployed Product returned:

- five login 200 responses and five current core reads;
- Data Steward, Manager and Admin: create 200, append DRAFT version 200, archive 200;
- Viewer and Developer mutation: 403;
- Data Steward review/publication spoof: 403;
- Data Steward hard delete: 403.

The accepted audit/history result is three archived DEV-only documents and six DRAFT versions.
The five disposable profiles are inactive, their credentials are disabled, and their active session
count is zero. The inspection `admin` remains active, login-enabled, role `admin`, maximum grade
`restricted`, failed attempts 0 and not locked. It was not reset, revoked or treated as disposable.
Current session observations are split as validation/test 0, inspection admin 0, other 0.

The MCL source/checkpoint/ledger/CR-link invariants remain `2/2/66/4`; active Table grants remain 0.

## Registration durable-storage decision — READ ONLY

No Registration schema or provider-apply mutation was performed.

Current Node POC preparation is process memory (`frontend/poc-server.mjs:130`) and its execution
mutates the same in-memory entry (`frontend/poc-server.mjs:4376-4408`). Candidate-to-CR currently
starts from that entry (`frontend/poc-server.mjs:5111`) and stores only CR plus opaque binding in the
coarse core JSON CAS (`frontend/poc-server.mjs:5181-5319`). `poc_state` is one JSON value and version
per scope (`frontend/poc-state-store.mjs:350-355`), protected by a scope/core CAS rather than
append-only row identities (`frontend/poc-state-store.mjs:441-523`).

Option A, placing preparation/receipt/candidate state into that global JSON blob, is not recommended:
it would not provide the accepted row-level immutable receipt, candidate identity, uniqueness,
retention and lease/fence semantics and would make unrelated core writes contend on one aggregate.

Option B is recommended, subject to explicit schema approval: reuse the already accepted canonical
relational contract rather than inventing another design.

- ADR-0016 requires a durable QUEUED→READY preparation with lease/fence and three append-only layers:
  receipt, deterministic typed candidates and unique candidate→CR provenance
  (`docs/adr/0016-durable-typed-bulk-registration-binding.md:26-45`).
- Candidate→CR creation must atomically persist CR, provenance, outbox and idempotency result
  (`docs/adr/0016-durable-typed-bulk-registration-binding.md:54-58`).
- The accepted legacy backend already names additive migrations `0046`, `0047` and `0048` for
  execution controls, immutable worker-call receipts and provider-apply fencing
  (`docs/adr/0041-accountable-registration-execution-and-evidence.md:143-170`).
- Existing CR/Governance apply owns provider mutation; Registration remains preparation plus governed
  CR creation (`docs/adr/0041-accountable-registration-execution-and-evidence.md:104-111`).

The minimum proposed entity responsibilities are therefore:

1. preparation/receipt: immutable input/config hashes, bounded lifecycle, attempt/progress,
   lease/fence and timestamps;
2. candidate: receipt FK, ordinal, target identity, typed operation and candidate hash;
3. candidate→CR provenance/idempotency: unique candidate, unique CR/item and request/idempotency
   hashes.

No second apply engine, scheduler, queue or worker is proposed. Migration remains
`HOLD_REGISTRATION_DURABLE_STORAGE_DECISION` until the user approves this direction.

## GX contract recovery

Read-only recovery confirmed the pinned `great-expectations==1.19.1`, quality worker/compiler,
datasource/checkpoint/result seams and documented DataHub integration requirements. Repository
history and clean-worktree search did not find executable `DataHubValidationAction`/emitter code or
an Assertion URN→GMS→DataHub UI receipt. Direct PREP/OPS mutation was not requested or performed.

Status is now `GX_PREP_OPS_CONTRACT_EVIDENCE_REQUIRED`. The missing evidence is limited to:

1. exact PREP/OPS quality-worker image/package/deployment receipt;
2. actual datasource/checkpoint/expectation configuration and execution/scheduler identity;
3. DataHub Validation Action/emitter configuration with platform instance, environment and secret
   reference but no secret value;
4. one sanitized checkpoint result plus Assertion URN, GMS write and UI Quality/Assertion receipt.

No GX version upgrade, Quality architecture or synthetic assertion path was created.

## AGY usage

| Task | Requested/effective | Result |
|---|---|---|
| Governance critical mutation | Claude Sonnet 4.6 Thinking / Claude Sonnet 4.6 Thinking | explicit Individual quota exhaustion before command or mutation |
| First fallback | Gemini 3.1 Pro High / Gemini 3.1 Pro High | fenced before mutation after reading the forbidden worktree; all claims discarded |
| Exact-worktree fallback | Gemini 3.1 Pro High / Gemini 3.1 Pro High | produced a bounded diff; coordinator rejected its global `knowledge.manage` widening and repaired/revalidated the final source |
| Registration/GX audits | Gemini 3.1 Pro High / Gemini 3.1 Pro High | read-only evidence; coordinator independently corrected the Registration recommendation from accepted ADRs |

## Overengineering check

```text
new tables        0
new dependencies  0
new services      0
new containers    0
new queues        0
new workers       0
new frameworks    0
new capabilities  0 (still exactly 15)
```

## Canonical status

- Governance policy/standard document read/create/DRAFT-update/archive:
  `COMPLETE_RUNTIME_VERIFIED`
- Registration overall: `PARTIAL`; durable relational direction awaits explicit approval.
- Governed Registration provider apply: `NOT_STARTED`; existing CR apply remains the owner.
- GX result→DataHub Assertion: `BLOCKED`, evidence required as listed above.
- Chat General/Vector/AUTO: unchanged completed baseline; no Chat mutation in this slice.
- Knowledge/Quality Product: `USER_FEATURE_DEFINITION_REQUIRED`.
- PHASE 1D overall: `PARTIAL`; this slice does not falsely close Graph/GX/provider traversal gaps.
