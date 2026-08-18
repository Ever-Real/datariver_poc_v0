# DEV Knowledge K2 Registry / Asset / Version runtime evidence

Date: 2026-08-18 KST  
Authoritative runtime: Node POC  
Authoritative worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`  
Product SHA: `68af3d5895a9ee553bff94e17c7a7d6cea47704a`  
Deployed OCI revision: `68af3d5895a9ee553bff94e17c7a7d6cea47704a`

## Scope and status

- Knowledge K1 exact identity/provenance and the completed Chat Router slice stayed frozen.
- This slice closes only the current Node K2 Registry / Asset / Version lifecycle.
- K2 bounded lifecycle status: `COMPLETE_RUNTIME_VERIFIED`.
- Knowledge overall remains `PARTIAL`; K3 through K9 were not started by this slice.

## Pre-K2 audits

### Node 108 → 107 reconciliation

- The `test:poc-server` command still executes the same twelve explicit Node test files.
- No test is skipped or marked TODO.
- Product `601a7ec14fbaa9af2068671e6777206c96a3c19b` intentionally replaced two pre-K7 Graph tests with one stronger DataHub-lineage-only contract:
  - the former generic Neo4j plus DataHub evidence test; and
  - the former optional-Neo4j-unavailable fallback test
  became one test that requires DataHub lineage, forbids generic Knowledge Graph evidence and proves no generic Neo4j traversal call.
- The provider-file inventory therefore changed from 22 to 21 and the stable full Node inventory from 108 to 107. This is a normal source inventory change, not a deleted security assertion, skip, TODO or runner drift.
- Product mutation for this audit: none.

### Provider probe parallel reset

- Two `ECONNRESET` results occurred only while provider capability probes ran in parallel.
- The same focused probe and the serialized full suite pass.
- Classification: `NODE_PROVIDER_PROBE_PARALLEL_FLAKINESS`.
- It is non-blocking while the focused/serialized contract remains green. No test framework or provider architecture was changed.

## Product behavior

- Registry columns are exactly:
  `No | 지식그래프명 | Version + badge | 설명 | 최근 수정일 | 생성자 | 최근 수정자 | 편집`.
- An empty Registry explains Asset, Draft and Active and presents an actionable create CTA only to an authorized manager.
- Asset detail groups releases/drafts under one canonical Asset identity and shows current version, immutable history, actors, source/provenance, bound Tables, graph preview and validation.
- Draft writes use server ETag/CAS. Creator and recent editor come from the authenticated subject.
- Publish keeps the existing independent-review contract; author self-publish is rejected.
- An Asset has at most one Active release. Editing Active creates the next Draft while the Active release remains unchanged.
- Archive is soft lifecycle state: history remains, the child Draft is discarded, and edit/archive actions disappear. No hard delete or direct Neo4j cleanup was added.
- Archived Assets are excluded from the Knowledge Chat Asset selector.
- Read-only users receive Registry/detail projections but no create/edit/archive action. A direct Studio deep-link without mutation capability is rerouted away from the mutation UI.

## Browser runtime E2E

One explicitly disposable DEV Asset named `K2 DEV Registry E2E 20260818` was used.

1. The inspection Admin created the Asset and saved its first Draft.
2. A hard reload restored the same server Draft and description.
3. Creator and recent editor displayed authenticated subject identities.
4. A separate disposable Admin reviewer opened the REVIEW Draft, completed Pre-flight and published with a review reason.
5. Registry and detail showed `v1 ACTIVE` and the independent reviewer.
6. Editing Active created `v2 DRAFT`; `v1 ACTIVE` remained visible in version history.
7. Archive confirmation produced `v1 ARCHIVED`, retained release/provenance history and removed mutation actions.
8. Knowledge Chat listed the existing Active K1 evidence Asset but did not list the archived K2 Asset.
9. A disposable Viewer saw read-only Registry/detail state, no create button and no mutation actions; direct Studio deep-link access was denied/rerouted.
10. Desktop and an actual iPhone 12 emulation pass covered Registry/detail/read-only layout and reachable actions.

The K2 evidence Asset remains archived as retained audit history. It was not hard-deleted and K1 evidence state was not changed.

## Account/session hygiene

- Inspection Admin: active, login-enabled, role `admin`, maximum grade `restricted`, failed attempts 0, not locked. `/auth/me` returned 200.
- Inspection Admin password/credential was not reset, reconstructed or logged.
- Exact disposable reviewer/viewer subjects were inactivated and their exact sessions revoked.
- Final validation/test active sessions: 0.
- Inspection Admin active sessions: 2.
- Other active sessions: 0.
- Browser-only disposable profiles were removed after their server sessions were revoked.

## Source validation

- Focused Knowledge tests: 4 files, 37/37 PASS.
- Node POC stable serialized suite: 107/107 PASS using the canonical isolated `POC_ENV_FILE` command.
- Frontend full suite: 87 files, 610/610 PASS with the established single-worker baseline.
- Lint: PASS.
- Typecheck: PASS.
- Production POC build: PASS; the existing Vite chunk-size warning remains a technical backlog item.
- Compose two-file no-interpolate render: PASS.
- `git diff --check`: PASS.
- Product image label equals the exact 40-character Product SHA and Web health is `ok` at `http://127.0.0.1:39083`.

## Independent validation

- Validator role: fresh, read-only Node POC reviewer.
- Requested/effective model: Gemini 3.1 Pro High (High).
- First dispatch `ctx_e338f4a8f530` was fenced and its result discarded because it attempted a forbidden
  full `docker inspect`. No claim or observation from that dispatch is completion evidence.
- Replacement dispatch `ctx_2a7bc18da445` started in the exact authoritative worktree and used only
  the OCI revision label format plus canonical `/healthz` for runtime inspection.
- Result: `PASS`.
- The replacement independently confirmed Product/OCI equality, healthy Node POC runtime, Node
  107/107, the exact eight Registry columns, the K2 Asset/version lifecycle guards and zero new
  table/framework. Files modified: none.
- Legacy FastAPI, environment dumps, guessed credentials and secret inspection were not used by the
  accepted Validator.

## Known risks and backlog

- `FRONTEND_ASYNC_TEST_PARALLEL_FLAKINESS`: current stable evidence remains the 87-file single-worker suite.
- `NODE_PROVIDER_PROBE_PARALLEL_FLAKINESS`: two parallel-only reset receipts; serialized/focused PASS remains authoritative.
- `CHANGE_MONITORING_LEDGER_SURFACE_RELOCATION`: non-blocking `NEXT_SLICE_FEEDBACK`, unchanged.
- `KNOWLEDGE_SECURITY_GRADE_CANONICAL_REALIGNMENT`: current Knowledge Studio still exposes legacy `PUBLIC / INTERNAL / CONFIDENTIAL / RESTRICTED` classification terminology while the DataRiver canonical security order is `normal < credential < restricted`. This slice did not invent or silently migrate security semantics. The vocabulary and request-time enforcement boundary require a small explicit follow-up before claiming canonical Knowledge grade UX.

## Overengineering check

```text
new tables       0
new dependencies 0
new services     0
new containers   0
new queues       0
new Product workers 0
new frameworks   0
new capabilities 0
```

No push, G1/G2 publication, PREP/OPS mutation, migration, K3+ Product mutation, new Graph framework or generic IAM/ACL work was performed.
