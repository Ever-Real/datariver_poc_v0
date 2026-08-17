# CURRENT.md — DataRiver Node POC Account / Access

## Current baseline

- Current Product SHA: `773cd37e6d48cbba02c999380fe1965a3b9f4e26`
- Deployed OCI revision: `773cd37e6d48cbba02c999380fe1965a3b9f4e26`
- PHASE 1A frozen Product: `618b9713059ba7e31b807ceae3b401766a313668`
- PHASE 1B Product: `e13dbb4f8412937e1d60bd45f83e0e91dc3e91aa`
- PHASE 1C-1 Product: `60f5f270a56130f2ed96236d9286d0903e3360db`
- PHASE 1C-2 Product: `f78f30fbcf0a5468ec2ce9893d06825ddd030369`
- PHASE 1C-3 Product: `9df97f4975a990819db655b74b09e709dc6d5aad`
- PHASE 1C-4 implementation: `65ca6349cc6f3c81a1ef75a48a7bb2b47e5a66c9`
- PHASE 1C-4 browser-origin hardening/current Product:
  `773cd37e6d48cbba02c999380fe1965a3b9f4e26`
- Web: healthy at canonical DEV origin `http://127.0.0.1:39083`
- G1/G2 publication, PREP/OPS mutation and push were not performed.

## Canonical status

- PHASE 1A local account/server session: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1B central capability/route authorization: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1C-1 System master/exact Table↔System mapping: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1C-2 account/Table grant/grade administration: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1C-2H hardening: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1C-3 fixed feature-role-grade management: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1C-4 CR responsible-System/three-lane approval: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1D cross-feature data enforcement: `PARTIAL` — read-only surface audit complete; Product
  mutation/validation is the current slice.
- PHASE 1E/1F: `BACKLOG`
- remote-host network acceptance: `TARGET_RECHECK_REQUIRED`
- overall Account/Auth program: `PARTIAL`

## Current authority

```text
local credential + opaque server session
→ request-scoped subject_id
→ current access document
→ central 15 capabilities
→ explicit Table grant
→ normal < credential < restricted
→ fixed 8 × 5 × 3 feature policy
→ Responsible System only for workflow/business features
→ feature operation
```

- Role/System authority stays in `change-history-access-v1`; credential/session rows contain only
  authentication data.
- User↔Table grants use the bounded exact `(subject_id, canonical dataset URN)` relation.
- Exact Table↔System is the current mapping authority for new CRs. Legacy schema scopes are not
  unioned or dual-written.
- A new CR is tied to one exact responsible System. Developer/Data Steward workflow actions use
  current assignments independent of priority. Final completion needs independent Developer,
  Data Steward and Manager lanes; Admin cannot silently substitute for them.
- Historical CRs without the new lane contract remain readable and mutation-protected. History was
  not rewritten.

## Inspection Admin and browser contract

- The DEV-only `admin` inspection account remains active, login-enabled, role `admin`, maximum
  grade `restricted`, with no Responsible System. It is explicitly excluded from validation cleanup.
- Its credential is server-valid and was verified through the actual browser flow. The password was
  not reset during browser diagnosis and is not stored in Git/evidence/dashboard.
- Canonical browser address is `http://127.0.0.1:39083`. Browser GET/HEAD requests received at
  `localhost` are redirected to that configured origin; state-changing wrong-Origin requests remain
  denied. Origin/CSRF/cookie controls were not relaxed.
- Agent browser flow is verified through login, `/auth/me`, Admin menu/page and hard reload. User
  browser confirmation remains pending; an active session is not treated as confirmation.

## Fresh validation

- Independent fresh Validator PASS at exact Product
  `773cd37e6d48cbba02c999380fe1965a3b9f4e26` and matching deployed OCI revision.
- Node POC full suite: 92/92 PASS.
- Frontend full suite: 87 files, 592/592 PASS on the final clean rerun.
- Lint, typecheck, production build, Compose no-interpolate render and `git diff --check`: PASS.
- Canonical GET 200; noncanonical browser GET 307; wrong-Origin login POST 403.
- Web/Airflow/Neo4j/PostgreSQL/Redis/MinIO host listeners remain loopback-bound. A real second-host
  denial probe is still required.
- MCL ledger/checkpoint/CR-link/source counts remained 46/2/4/2 through PHASE 1C-4 validation.

## PHASE 1D current slice

- Reuse the existing grants, grade helper, fixed policy, capabilities and exact workflow System
  mapping. No new auth table, service, dependency or policy framework is required.
- Replace schema/System-based general data visibility with one bounded request-time Table decision.
- Enforce before local search/count and vector ranking. Constrain graph/Chat inputs before
  traversal/context where canonical Table identity is provable.
- Keep Responsible System out of general Catalog/Monitoring/Governance reads; use it only for
  Registration/Knowledge/Quality/Change workflow operations.
- Fail closed for non-Table identities, unresolved current grades, deleted/current-missing assets
  and graph nodes without proven canonical Table identity.
- Provider-side lineage/glossary filtering, deleted-asset grade history, Neo4j identity provenance
  and coarse unbound Knowledge/Governance blobs remain explicit risks; do not claim false runtime
  completeness.

## Gates

- G1 SOURCE_MERGE: `NOT_APPROVED`
- G2 DEV_PUBLISH: `NOT_APPROVED`
- G3 PREP mutation: `NOT_APPROVED`
- G4 OPS mutation: `NOT_APPROVED`
- Next smallest Product slice: PHASE 1D bounded Table decision + Catalog/Search/Vector/Chat
  enforcement, followed by focused runtime validation.
