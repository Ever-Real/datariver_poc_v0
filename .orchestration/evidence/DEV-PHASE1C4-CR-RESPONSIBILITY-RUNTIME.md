# DEV PHASE 1C-4 CR responsibility and three-lane approval runtime evidence

## Identity and scope

- Fresh observation: `2026-08-17T10:59:11+09:00` (`Asia/Seoul`)
- Product SHA: `773cd37e6d48cbba02c999380fe1965a3b9f4e26`
- PHASE 1C-4 implementation commit: `65ca6349cc6f3c81a1ef75a48a7bb2b47e5a66c9`
- Browser-origin hardening commit: `773cd37e6d48cbba02c999380fe1965a3b9f4e26`
- Deployed OCI revision: `773cd37e6d48cbba02c999380fe1965a3b9f4e26`
- Runtime: `datariver-poc-web-1`, image `datariver-poc:local`, health `healthy`
- Environment: authoritative local DEV only; PREP/OPS were not read or mutated
- Git/release: no push, merge, publication, G1/G2/G3/G4, migration, schema change or legacy deletion

This evidence covers PHASE 1C-4 only. It does not claim PHASE 1D cross-feature data filtering,
PHASE 1E retirement, PHASE 1F final acceptance, remote-host network denial, GX availability or
provider readiness.

## AGY and validation receipts

- Orca Run: `run_d05f117889c1`.
- Claude preflight task `task_a03da30e84dd`: requested/effective model both Claude Sonnet 4.6
  (Thinking); correct worktree and then-current clean baseline verified.
- Claude builder task `task_e08b12c06842`: stopped after an explicit individual-quota exhaustion
  response. The failure was not inferred from a timeout or model substitution.
- Gemini safe continuation task `task_d90d90b82ad4`: requested/effective model both Gemini 3.1 Pro
  High. Its partial implementation/test handoff was coordinator-reviewed; the coordinator repaired
  the remaining boundary, completed tests and fixed the Docker image copy contract.
- A later AGY read-only report was rejected as evidence because it mixed legacy FastAPI
  `backend/governance.py` with the current Node POC and incorrectly reported no running container.
  No historical or wrong-runtime PASS was reused.
- Fresh independent Node POC validation: recorded below after direct source/runtime recheck; no
  Product or DEV data mutation was delegated to the Validator.
- The final fresh Validator checked the exact Product SHA
  `773cd37e6d48cbba02c999380fe1965a3b9f4e26`, a clean worktree, the exact deployed OCI revision,
  local/deployed checksums, current Node sources and live DEV HTTP behavior. It returned PASS.

## Implemented authorization contract

The Product adds no capability, table, dependency, service, policy engine or workflow framework.
It reuses the existing core-state CAS, exact Table grant, security-grade helper, fixed feature
policy, exact Table-to-System mapping and request-time principal.

### Create

- `frontend/poc-server.mjs:4900-5007` accepts exactly one current canonical Table URN and one
  responsible System, rejects protected client authority claims, and verifies current DataHub
  Table type/grade before mutation.
- A non-Admin creator needs an active explicit Table grant, sufficient maximum grade, and an
  allowed fixed `change` policy cell (`frontend/poc-cr-lifecycle.mjs:59-70`). Admin retains the
  approved application-wide data scope.
- The responsible System comes only from active exact Table-URN mappings. Legacy
  `system_schema_scopes` is not a new-CR authority and is not unioned or dual-written
  (`frontend/poc-cr-lifecycle.mjs:72-82`).
- The requester, round submitter, item routing and history actor come from the request principal;
  client role/subject/System/grant/grade/capability values are not accepted.

### Workflow and completion

- Developer/Data Steward review, re-request, proceed and test operations require the current role
  and current assignment to the CR's responsible System. Priority is not an authorization tier
  (`frontend/poc-cr-lifecycle.mjs:84-89`).
- Final completion uses three independent current-round lanes: `DEVELOPER`, `DATA_STEWARD`, and
  `MANAGER` (`frontend/poc-cr-lifecycle.mjs:7-8,97-110,129-141`). Admin satisfies none of them.
- A valid third lane appends exactly one `COMPLETED` transition; two lanes remain incomplete.
  Duplicate-lane requests are idempotent and concurrent stale writers lose the existing core CAS
  (`frontend/poc-server.mjs:5045-5097`).
- Existing CRs without `approval_lanes` remain readable and receive a bounded
  `CR_LEGACY_COMPATIBILITY_ONLY` mutation result. Historical rows are not rewritten
  (`frontend/poc-server.mjs:5023-5037`).

### Browser adapter

- New CR creation and lifecycle commands use the exact server routes and current core ETag
  (`frontend/src/poc/pocApi.ts:2320-2349,2467-2503`).
- The adapter replaces only the returned record and advances the returned ETag; it does not write
  its stale whole-core snapshot after the server mutation.
- The old fixed-actor browser path remains only for `pocState=false` legacy compatibility. It is not
  reachable as the deployed Node POC authority for new server-owned CRs.

## Route and storage impact

- Registry: 63 explicit route IDs: 7 `ANONYMOUS`, 2 `AUTHENTICATED`, 52
  `CAPABILITY_PROTECTED`, 1 `INTERNAL_SERVICE`, 1 `DISABLED`, 0 unknown/ambiguous.
- New exact routes: POST `/poc-api/change-requests`, GET
  `/poc-api/change-requests/:id`, POST `/poc-api/change-requests/:id/commands`.
- Capabilities remain exactly 15. Create uses existing `change.read`; commands use existing
  `change.execute` plus current resource checks.
- New DB table/schema/dependency/service/container: 0. Approval lanes live in the existing bounded
  CR record inside the versioned core document.

## Coordinator tests at the Product SHA

| Command / probe | Fresh result |
|---|---|
| `npm run test:poc-server` | PASS — 92/92 Node tests |
| `npm test` | PASS — 87 files, 592/592 tests on the final clean rerun |
| `node --test poc-server.auth.test.mjs` | PASS — 9/9 focused auth/origin tests |
| focused browser auth adapter | PASS — 10/10 tests |
| fresh Validator focused Node tests | PASS — 46/46 |
| fresh Validator focused frontend tests | PASS — 3 files, 37/37 |
| `npm run lint` | PASS |
| `npm run typecheck` | PASS |
| `npm run build:poc` | PASS; existing `>500 kB` advisory remains |
| `git diff --check` | PASS |
| `docker compose -f deploy/poc/docker-compose.poc.yaml config --no-interpolate --quiet` | PASS |
| normal Compose render without secret injection | not claimed; required local secret variables were intentionally not exported into the validation command |
| OCI revision/health/port inspect | Product revision exact; healthy; `127.0.0.1:39083` |
| protected-secret scan | no inspection password in Git; expected generic `temporary-password` API documentation/tests only |

Focused Node tests cover current Table/grant/grade/policy/exact mapping create, wrong System,
priority-independent actions, Manager lane, Admin denial, actor spoof, legacy reads, stale CAS,
concurrent same-lane writers and exactly-once completion.

The first full frontend attempt encountered one unrelated Governance timing failure. The same test
passed in isolation, and the final clean full-suite rerun passed all 592 tests. No historical PASS
was substituted for the final rerun.

## Browser login root cause and hardening

- The same frozen inspection credential succeeded through the actual Orca browser at the canonical
  DEV origin `http://127.0.0.1:39083`: login POST 200, browser cookie persistence, `/auth/me` 200,
  Admin menu/page visibility and hard-reload persistence all passed.
- The same credential failed only when the browser opened `http://localhost:39083`: the server
  correctly returned `403 ORIGIN_FORBIDDEN`, because `localhost` and `127.0.0.1` are different
  origins and the canonical public origin is exact.
- The credential was not reset. Origin, CSRF, cookie and password controls were not weakened.
- Noncanonical browser GET/HEAD requests now return a no-store 307 redirect to the configured
  canonical public origin while preserving path/query. State-changing requests are never
  redirected; a wrong-Origin login POST remains 403.
- The SPA now explains exact `ORIGIN_FORBIDDEN` failures with the configured DEV address instead of
  mislabeling them as a credential failure. Other login errors retain the generic response.
- Final live probes: canonical GET 200, noncanonical GET 307, wrong-Origin login POST 403. The
  current deployed OCI revision exactly matches the Product SHA.
- Status is `SERVER_VERIFIED` and `BROWSER_FLOW_VERIFIED`; the user's own successful retry remains
  `USER_CONFIRMATION_PENDING` and is not inferred from an active session.

## DEV representative runtime matrix

Disposable DEV users and random passwords were created through the official operator/Admin paths.
Passwords, cookies, Table identities and subject IDs were not written to this evidence.

```json
{"viewer_create":true,"wrong_system_denied":true,"lower_priority_allowed":true,"developer_lane":true,"steward_lane":true,"manager_lane":true,"admin_bypass_denied":true,"three_lane_complete":true,"dummy_users":8,"cleanup":true}
```

The test covered viewer creation, a wrong-System Developer denial, priority-2 Developer/Steward
acceptance, Developer/Steward/Manager final lanes, Admin silent-bypass denial and completion only
after all three lanes. The resulting test CR is retained as history. Temporary credentials were
disabled, sessions revoked, active grants removed and temporary exact mappings removed.

## Inspection Admin

- The DEV-only `admin` inspection account is active, login-enabled, role `admin`, maximum grade
  `restricted`, with no Responsible System assignment.
- Its password was reset only through an official temporary operator plus Admin credential API.
  The credential transaction revoked the preceding session; the new credential completed a real
  `/auth/login` and `/auth/me` check. The verification session was then logged out.
- The temporary reset operators were credential-disabled and made inactive. The inspection account
  is explicitly excluded from validation cleanup.
- The plaintext temporary password was handed to the user once outside this evidence and was
  removed from external secret files. It is not recoverable from Git, this evidence or the dashboard.
- A final read-only database observation confirmed `failed_attempts=0`, no active lock and one
  non-revoked unexpired session. That session was not revoked because the inspection account is not
  a validation dummy; its owner cannot be inferred from the row alone.

## Sanitized final DEV observation

- local credentials: 63 historical rows; 1 enabled (inspection Admin)
- local sessions: 97 historical rows; 1 active at the final read-only observation
- User-to-Table grants: 20 historical rows; 0 active
- exact Table-to-System mappings: version 6; 0 active
- access document version: 114
- core Change Requests: 2 (including the retained completed validation CR)
- MCL ledger/checkpoints/CR links/sources: 46 / 2 / 4 / 2, unchanged
- feature policy: version 6; fixed 120 cells, unchanged

## Security negatives

- unknown/malformed/current-provider-unavailable Table creation: fail closed
- missing grant, insufficient grade, fixed feature-policy deny: 403
- wrong/non-responsible System workflow actor: 403
- Admin workflow/final-lane attempt: 403
- client role/subject/System/grant/grade/capability claims: no authority change
- stale core ETag: 409
- concurrent same-lane approval: one commit, one stale conflict; no duplicate lane/completion
- two final lanes: incomplete; third valid lane: one completion
- direct protected API without session remains 401; unknown API remains JSON 404

## Regression and remaining risks

- Local auth/session, request principal, access/core CAS, Table grant, security grade, fixed policy,
  System master/mapping, Catalog/Search/Tree, Change History/CR, Monitoring, Chat authentication,
  MCL ledger/checkpoints, Airflow exact service route and loopback bind passed their current tests.
- A real second-host network denial remains `TARGET_RECHECK_REQUIRED`.
- PHASE 1D is not implemented by this Product. Catalog/search/count/vector/graph/Chat/Knowledge/
  Quality/Monitoring/Governance cross-feature Table filtering must not reuse this PASS.
- Historical CRs remain compatibility-read-only on the new server command boundary. A separate
  conversion contract would require explicit product approval; history was not rewritten here.
- Existing Vite chunk-size, provider/vector/GX and reproducible deployment backlogs are unchanged.
- During final validation, explicitly identified multi-hour/day-old orphan Node test processes were
  terminated without touching Product/container processes. The final full suite then completed on
  one clean coordinator run.

## Canonical status

- PHASE 1C-4: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1D: `BACKLOG`
- remote-host network acceptance: `TARGET_RECHECK_REQUIRED`
- overall Account/Auth program: `PARTIAL`

Next Product slice: PHASE 1D actual data-access enforcement only.
