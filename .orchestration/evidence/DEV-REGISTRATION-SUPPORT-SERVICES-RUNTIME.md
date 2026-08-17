# DEV Registration / Support Services runtime evidence

## Baseline

- Authoritative worktree:
  `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
- Branch: `Ever-Real/dev-core-t04-validation`
- Evidence base before the Product change:
  `dd08ca43cd18d3b07bc5a253c1f8616c9c0772e8`
- Product SHA and deployed OCI revision:
  `d424d0e49e2f5b763a77cd4f2beb438e5345b0fa`
- Runtime: authoritative Node POC, healthy at `http://127.0.0.1:39083`
- No push, G1/G2 publication, PREP/OPS mutation, migration, provider upgrade or destructive
  cleanup was performed.

The Account/Auth, CR, PHASE 1D-R and MCL automatic-detection baselines were not redesigned. This
slice connects the existing Registration paths to their already-established feature and data
authority and records the current support-service gate.

## DEV support-service gate

| Service | Current DEV evidence | Status |
|---|---|---|
| Airflow | Airflow 3.3.0, existing `datariver_bulk_registration_prepare` DAG, loopback port 18888, supported Web URL/auth/callback binding and an actual Product-triggered callback to `READY` | `COMPLETE_RUNTIME_VERIFIED` |
| MinIO | Existing pinned image `RELEASE.2025-09-07T16-13-09Z`, loopback ports 9000/9001, existing external DEV endpoint/secret contract, five expected buckets, actual Product part/complete and object cleanup | `COMPLETE_RUNTIME_VERIFIED` for the existing DEV external-dependency contract |
| GX | Exact `great-expectations==1.19.1` worker/compiler execution seam is present; result-to-DataHub Assertion emission and a GMS/UI Assertion receipt are not implemented or runtime-proven | `IMPLEMENTED_NOT_VERIFIED` / `PARTIAL` |

Airflow and MinIO were bound through the existing ignored DEV configuration/secret boundary. No
secret value is recorded here. No service, container architecture, provider or version was added.
MinIO remains an external DEV dependency rather than being silently re-owned by this Compose
project.

## Registration authority

The bounded Registration decision for a non-Admin is:

```text
active current principal with role data_steward or manager
AND current canonical TABLE
AND active exact User↔Table grant
AND user maximum grade >= current Table grade
AND fixed registration-role-grade policy cell = Allow
AND at least one exact active Table↔System mapping assigned to the current principal
```

Admin bypasses the grant, grade, feature-data and Responsible-System restrictions, but does not
bypass malformed identity, non-TABLE identity or current-provider integrity. Developer is denied
on the Registration human routes even if a generic Catalog capability is present.

The covered paths are template download, MinIO part/complete/accepted status, Bulk preparation
create/list, metadata candidates/preview and manual metadata. General Catalog, Search, Monitoring,
Governance and Chat reads continue to ignore Responsible System.

## AND truth-table and integrity evidence

Focused source tests pin the load-bearing conjunction:

| Grant | Grade | Fixed policy | Responsible System | Result |
|---|---|---|---|---|
| deny | allow | allow | assigned | deny |
| allow | deny | allow | assigned | deny |
| allow | allow | deny | assigned | deny |
| allow | allow | allow | missing/unassigned | deny |
| allow | allow | allow | assigned | allow |

The same test fixes Developer role denial, Admin data bypass, Admin malformed-grade denial,
Admin non-TABLE denial and empty/foreign active-System denial. Runtime additionally proved
immediate grant removal and exact Table↔System mapping removal without renewing the session.

## Request hydration and leakage boundary

- Bulk compilation reads one cached canonical current inventory and validates Table and Column
  identities from that inventory. It does not make one targeted DataHub request per input row.
- Candidate projection re-confirms current Tables in bounded batches and reads current mappings
  once per request. Grant and fixed-policy authority come from the request principal; there is no
  session permission snapshot.
- Candidate filtering occurs before paging, count and receipt projection. Visible candidate count,
  root hash and receipt hash are recomputed from the authorized projection.
- Preparation list/count is owner-scoped for non-Admin, 404-hides foreign ownership, allows Admin
  application-wide data access and immediately reprojects counts after grant or mapping changes.
- The internal `creatorSubjectId` owner marker is not returned to the browser.

This is bounded request-level hydration, not a new authorization or observability framework.

## Product runtime E2E

A coordinator-owned secret-bearing harness used four random, in-memory-only disposable DEV
credentials and one existing normal-grade current Table/System pair. No password, cookie, token,
business Table identity or secret was written to evidence, command arguments or a file.

The exact deployed Product produced:

- four successful logins;
- Developer template request: 403;
- MinIO part and complete: 200;
- Bulk preparation create: 202;
- actual Airflow service callback: preparation `READY`;
- creator/owner identifier absent from the public receipt;
- owner without the exact grant: candidates/items/count 0;
- full grant + grade + policy + System conjunction: candidates/items/count 1;
- foreign steward owner read: 404;
- Admin owner/data bypass: 200 with one visible item;
- immediate grant removal: candidate/count/preparation total 0;
- regrant followed by exact mapping removal: candidate/count 0.

The test deliberately stopped before applying metadata to DataHub or changing a business Table.
The exact temporary MinIO objects were deleted. Disposable credentials were disabled, sessions
revoked, grants and mappings deactivated, assignments removed and users made inactive. Final
cleanup observation was enabled credentials 0, active sessions 0, active users 0, assignments 0,
active grants 0 and active mappings 0 for those identities. Historical rows were not hard-deleted.
The inspection `admin` account was not used as a dummy and was not reset, disabled or cleaned.

## Regression and build

Final source at the Product SHA passed:

- focused authorization tests: 6/6;
- focused server tests: 22/22;
- canonical Node POC suite: 103/103;
- frontend suite: 87 files, 592/592;
- lint, typecheck, POC build and production build;
- Compose base + DataHub-provider overlay render;
- hardcoding/secret scan and `git diff --check`.

An initial ad-hoc wildcard Node invocation inherited the ignored DEV `.env` and produced two false
test failures. It is not accepted as canonical evidence. The tracked `test:poc-server` command now
sets a deliberately missing `POC_ENV_FILE`, so its 103-test result is independent of the caller's
DEV provider configuration. Product runtime semantics were not changed by that isolation.

After the exact image build, Web-only recreation preserved the canonical port and reported a
healthy container whose OCI revision exactly equals the Product SHA. Provider runtime flags for
DataHub, Airflow, MinIO, Chat, embedding and reranking were present. The final read-only baseline
kept the inspection Admin active/login-enabled with role `admin`, grade `restricted`, zero failed
attempts, no lock, one active session and no Responsible System. MCL source/checkpoint/ledger/CR-link
counts remained 2/2/66/4.

## Independent validation

The first attempted validator was discarded with `WRONG_WORKTREE_PROCESS_CWD` and made no change.
A fresh Gemini 3.1 Pro High (`high`) validator was then launched from the authoritative worktree.
It independently recorded the clean branch/HEAD, exact Product SHA, Node POC authority and healthy
runtime, ran the canonical suite at 103/103 PASS, and made no source or runtime mutation.

## Canonical status by product surface

| Surface | Status | Remaining boundary |
|---|---|---|
| Account/Auth core | `COMPLETE_RUNTIME_VERIFIED` | feature-specific regression only |
| Airflow DEV support | `COMPLETE_RUNTIME_VERIFIED` | PREP/OPS remain untested |
| MinIO DEV support | `COMPLETE_RUNTIME_VERIFIED` | existing external DEV ownership must stay explicit |
| GX execution seam | `IMPLEMENTED_NOT_VERIFIED` | DataHub Assertion egress and UI receipt |
| Registration bounded auth/preparation slice | `COMPLETE_RUNTIME_VERIFIED` | applies only to the covered existing preparation/candidate routes |
| Registration overall | `PARTIAL` | sparse manual-metadata read-back compatibility and remaining end-to-end apply workflow |
| Governance documents | `HOLD` | `HOLD_GOVERNANCE_DOCUMENT_MUTATION_POLICY` |
| Chat General / Vector / AUTO | `COMPLETE_RUNTIME_VERIFIED` | preserve current baseline |
| Chat Graph | `PARTIAL` | exact canonical Neo4j Table provenance |
| Knowledge Product | `USER_FEATURE_DEFINITION_REQUIRED` | documentation only before user definition |
| Quality Product | `USER_FEATURE_DEFINITION_REQUIRED` | GX readiness is a separate status |

The Account/Auth core is complete. PHASE 1D overall remains `PARTIAL` only because the named
Graph/provider/feature-owned surfaces are not all closed; they are not grounds for another core
authorization redesign.

## Holds and next smallest slices

- `HOLD_GOVERNANCE_DOCUMENT_MUTATION_POLICY`: the exact policy/standard document create/update/
  delete roles are not canonical. Active-user read remains available; no workflow was invented.
- GX: define and implement the smallest existing-contract result-to-DataHub Assertion egress slice
  only after the Quality feature boundary is confirmed.
- Registration: isolate the existing sparse manual-metadata DataHub empty domain/glossary read-back
  502 as a compatibility repair; do not mix it with authorization or support-service redesign.
- Chat: keep General/Vector/AUTO unchanged; resolve Graph identity in the Knowledge provenance phase.

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

