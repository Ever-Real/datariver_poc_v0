# DEV Registration READY candidate to governed CR runtime evidence

## Baseline

- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Evidence base before this Product slice:
  `66e250c29efacbad02dfaf9e5bfc38187d89fec0`
- Product SHA and deployed OCI revision:
  `5e600320e08da16c67dcb4c0e4dce76162230f04`
- Authoritative runtime: Node POC, healthy at `http://127.0.0.1:39083`
- Account/Auth, CR three-lane, PHASE 1D-R, MCL automatic detection, Airflow/MinIO support and
  Registration manual-metadata apply remain completed baselines. They were not redesigned.
- No push, G1/G2 publication, PREP/OPS mutation, migration, provider upgrade, business metadata
  write or destructive cleanup was performed.

## Bounded Product result

The existing Registration path now accepts one explicit command for one `READY` metadata
candidate and creates one server-authored governed CR. The browser no longer creates or stores a
candidate-derived CR locally. The authoritative Node route:

```text
POST /poc-api/bulk/uploads/{upload}/preparations/{preparation}/
     metadata-candidates/{candidate}/change-request
```

requires only a bounded title/reason, exact quoted preview ETag and `Idempotency-Key`. It re-runs
the preview and current authority checks before one core CAS. It never calls the DataHub apply
path.

The non-Admin decision is an exact conjunction:

```text
active current data_steward or manager
AND current canonical TABLE
AND active exact User-to-Table grant
AND user maximum grade >= current Table grade
AND fixed Registration role-grade policy cell = Allow
AND exact active Table-to-System mapping assigned to the principal
```

Admin retains application data bypass but not current-TABLE, mapping, input, ETag, idempotency or
CAS integrity. Responsible System remains a Registration/CR business scope and is not general
Catalog/Search/Monitoring/Governance/Chat visibility authority.

## Source and concurrency fences

- Missing, malformed and stale preview ETags return 428, 400 and 412 respectively.
- The request hash binds actor, upload/preparation/receipt/candidate evidence, current preview,
  fixed Aspect, before/after documents, current source version and responsible System.
- Same-key exact replay returns the original CR; the same key with changed input returns 409.
- A second key cannot create a second CR for the already-bound candidate.
- CAS creates exactly one CR and one internal candidate binding.
- The internal binding is removed from every public core projection, including Admin, and a core
  replacement preserves rather than browser-controls it.
- Raw provider documents, provider coordinates and the raw idempotency key are not persisted or
  returned.

This is a bounded Node POC enforcement slice. The current in-memory preparation lifecycle,
canonical durable outbox/provider-apply workflow, all typed multi-Aspect groups and target-host
external gates are not promoted to complete by this result.

## Actual Product runtime

A coordinator-owned harness used one random in-memory-only disposable Data Steward credential,
one existing current normal-grade Table and one active System. It created a temporary exact grant
and Table-to-System mapping only. No password, cookie, service token, subject identifier, Table
identity or provider content was written to a file, evidence or command argument.

The exact deployed Product returned:

| Operation | Result |
|---|---:|
| local login | 200 |
| MinIO part / complete | 200 / 200 |
| bulk preparation create | 202 |
| actual Airflow callback | `READY` |
| authorized candidate / preview | 1 item / 200 |
| immediate grant removal | 0 items; create 404 |
| immediate mapping removal | 0 items; create 404 |
| missing / malformed / stale ETag | 428 / 400 / 412 |
| first candidate-to-CR command | 201 |
| exact same-key replay | 200, same CR |
| changed same-key / second-key command | 409 / 409 |

The durable core observation increased by exactly one CR and one internal binding. A direct
DataHub `datasetProperties` fingerprint was identical before and after the command, proving that
this slice did not apply the proposed metadata to the provider.

## Cleanup and restart

- Exact quarantine and filefolder MinIO objects were deleted.
- The disposable credential was disabled and its session revoked.
- The exact grant and mapping were deactivated; assignment removed; user retained only as inactive
  history. No history row was hard-deleted.
- Web-only recreation cleared the in-memory preparation and restored the exact same Product image.
- Final disposable active users/assignments/credentials/sessions/grants/mappings were all zero.
- Inspection Admin remained active, login-enabled, role `admin`, grade `restricted`, failed
  attempts 0, unlocked, with zero Responsible Systems. It was not used or cleaned as a dummy.
- Final Catalog count remained 2,002 and MCL source/checkpoint/ledger/CR-link counts remained
  2/2/66/4.
- Web returned healthy on loopback and its OCI revision exactly matched the Product SHA.

## Source validation

Final source at the Product SHA passed:

- focused authorization/state/provider tests: 46/46;
- canonical Node POC suite: 105/105;
- frontend suite: 87 files, 593/593;
- lint, typecheck and POC production build;
- Compose no-interpolate render, sensitive-pattern scan and `git diff --check`.

The known existing Vite chunk-size warning remains a technical backlog item and was not introduced
by this slice.

## Independent validation

A fresh Gemini 3.1 Pro High read-only validator started from the authoritative worktree after the
exact Product deployment. Requested and effective model matched. It recorded exact pwd, Git root,
branch, HEAD and deployed OCI revision; explicitly used the Node POC rather than legacy FastAPI;
reviewed the authority, ETag/idempotency/CAS, hidden-binding and zero-provider-write contracts; and
ran the canonical Node POC suite with 105/105 PASS and zero blockers. It made no file, database,
runtime or container change.

One generated sentence also mentioned the unused 39080 default while correctly identifying the
39083 publish. That sentence is not accepted as runtime evidence. The coordinator independently
verified the only canonical DEV host port as 39083, health `ok` and the exact OCI revision.

## Canonical status

| Surface | Status | Boundary |
|---|---|---|
| Account/Auth core | `COMPLETE_RUNTIME_VERIFIED` | feature-specific regression only |
| Registration authorization/preparation | `COMPLETE_RUNTIME_VERIFIED` | existing Node POC path |
| Registration manual metadata apply | `COMPLETE_RUNTIME_VERIFIED` | bounded disposable provider apply |
| Registration READY candidate to governed CR | `COMPLETE_RUNTIME_VERIFIED` | one candidate, one CR, no provider write |
| Registration overall | `PARTIAL` | durable preparation/outbox/apply and remaining typed/target gates |
| GX Assertion egress | `IMPLEMENTED_NOT_VERIFIED` / `PARTIAL` | `GX_CANONICAL_RUNTIME_CONTRACT_REQUIRED` |
| Governance document mutation | `HOLD` | `HOLD_GOVERNANCE_DOCUMENT_MUTATION_POLICY` |
| Chat General / Vector / AUTO | `COMPLETE_RUNTIME_VERIFIED` | preserve baseline |
| Chat Graph | `PARTIAL` | canonical Neo4j Table provenance |
| Knowledge / Quality Product | `USER_FEATURE_DEFINITION_REQUIRED` | documentation only |
| PHASE 1D overall | `PARTIAL` | named graph/provider/feature-owned gaps |

## AGY usage

- Critical mutation fallback: Gemini 3.1 Pro High after previously recorded explicit Claude
  Sonnet 4.6 individual-quota exhaustion. Requested and effective Gemini model matched.
- The implementation worker result was not trusted alone; the coordinator reviewed and repaired
  the diff, reran all gates, committed, built, deployed and performed the secret-bearing runtime.
- One attempted validator placement was discarded before use because its displayed cwd was not
  authoritative. A fresh validator was then started with an explicit authoritative cwd.

No agent received a password, cookie, provider/service token or secret file.

## Holds and next smallest slice

- Do not infer a direct provider apply from CR creation. Read-only reconcile the remaining Node POC
  durability/outbox/apply gap against the canonical typed-bulk contract before any new mutation.
- Keep `GX_CANONICAL_RUNTIME_CONTRACT_REQUIRED` and
  `HOLD_GOVERNANCE_DOCUMENT_MUTATION_POLICY` unchanged.
- Do not start PHASE 1E/1F, Knowledge, Quality, GX architecture, migration or PREP/OPS work.

## Overengineering check

```text
new tables            0
new dependencies      0
new services          0
new containers        0
new provider versions 0
new frameworks        0
new capabilities      0
```

The Evidence SHA is the separate commit containing this file, `CURRENT.md`, the master backlog and
the Korean priority dashboard. It is reported after that commit is created and is not a Product SHA.
