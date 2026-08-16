# DEV PHASE 1B central authorization runtime evidence

## Scope and lineage

- Product SHA: `e13dbb4f8412937e1d60bd45f83e0e91dc3e91aa`
- PHASE 1A frozen Product SHA: `618b9713059ba7e31b807ceae3b401766a313668`
- PHASE 1A Evidence SHA: `8c1f93a456d0fe51e46987b72d66f563f6467d73`
- published `origin/dev`: `ef41447a1d470119c1a83280e261d4be411354ef`
- observation completed: `2026-08-16T16:16:35+09:00`
- environment: `DEV_MAC_ARM64`; Web image/runtime `linux/amd64`, Node `22.19.0`
- canonical status: PHASE 1B `COMPLETE_RUNTIME_VERIFIED`; overall Account/Auth `PARTIAL`
- release gates: G1/G2/G3/G4 `NOT_APPROVED`; no push, PREP mutation or OPS mutation

The Phase 1A local credential, opaque server session, request-scoped principal, access-document
authority and loopback/private-network boundary remain frozen. PHASE 1B adds one bounded
role-to-capability policy and optional System scope. It does not add an IAM service, permission
database, workspace, OIDC, Keycloak, policy DSL, role hierarchy or sensitivity policy.

## Precheck

### Validation accounts

The two PHASE 1A accounts were validation-only DEV human fixtures: both credentials were enabled at
precheck, their passwords had already been destroyed, and all four prior sessions were revoked.
Five fresh validation accounts were then created through the official access CAS/operator bootstrap
path for `admin`, `viewer`, `developer`, `data_steward` and `manager` runtime checks. After validation,
the official version-guarded operator command disabled all seven credentials and revoked every active
session. Access users and historical references were preserved; no credential was created for a
synthetic `checkpoint-*` subject.

Final read-only aggregate:

| Item | Result |
|---|---:|
| local credentials | 7 |
| login-enabled credentials | 0 |
| local sessions | 14 |
| active sessions | 0 |
| access users | 11 |

### Machine consumers

| Consumer | Classification | PHASE 1B result |
|---|---|---|
| Scheduler | internal same-process | source-compatible; currently disabled |
| MCL capture | internal same-process | source-compatible; current bindings `0/9`, not run |
| DataHub inventory/embedding | internal same-process outbound adapter | authenticated browser fence does not block it |
| Airflow bulk preparation | service-to-service | exact service-token route retained; token cannot call general APIs |
| other Airflow source DAGs | future/not mounted | add exact service routes only if activated later |
| provider callbacks | disabled/absent | no new machine credential |
| Browserless | future/not active | no new machine credential |
| GX | future/not active in this POC | no fabricated runtime evidence |
| MinIO | internal outbound adapter | provider config `0/3`; browser routes capability-protected |
| bootstrap/MCL CLI | direct module/storage call | no browser cookie dependency |

### Network

Web, Airflow, PostgreSQL, Redis, Neo4j and the owned connector ports remain bound to loopback or
private Compose networks. The authoritative Web publish is `127.0.0.1:39083`. A remote-host denial
probe was not available, so that target remains `TARGET_RECHECK_REQUIRED`.

## Authorization design

Every protected request follows:

```text
local opaque session
→ request-scoped subject_id
→ current change-history-access-v1 document
→ active role
→ central capability
→ optional current System assignment
→ feature operation
```

The session, credential tables, browser storage, query, body and custom headers do not own role or
System authority. Admin receives every application capability and global application System scope
inside the central module; this does not grant host, database-superuser, infrastructure-secret,
PREP/OPS or G3/G4 authority.

The manager policy follows accepted
`docs/adr/0107-server-managed-profile-role-authority.md`, introduced by commit
`f2e2e79c0b3cfcc93aa8afda3c44eb48af70f983`, especially lines 18–25 and 49–52:
manager inherits engineering/steward operations and adds Knowledge/Governance manage/review.

## Canonical capability policy

Exactly 15 capabilities are defined in `frontend/poc-authorization.mjs`:

| Capability | Purpose |
|---|---|
| `catalog.read` | catalog/search/tree/detail and catalog-derived reads |
| `catalog.execute` | bounded catalog preparation/upload execution |
| `catalog.manage` | metadata mutation |
| `chat.query` | General/Vector/Graph Chat routes and stream |
| `change.read` | Change History/CR/history summary reads |
| `change.execute` | assigned-System Change operations |
| `change.manage` | assigned-System Change governance mutation |
| `monitoring.read` | monitoring/provider capability inventory |
| `knowledge.read` | Knowledge/Governance reads |
| `knowledge.manage` | Knowledge/Governance mutation |
| `knowledge.review` | Knowledge/Governance review |
| `quality.read` | Quality/profile coverage reads |
| `quality.execute` | Quality execution seam |
| `quality.manage` | Quality definition/manage seam |
| `admin.manage` | application User/System/access and operator routes |

### Role → capability matrix

| Role | Capability set | Count | System semantics |
|---|---|---:|---|
| `viewer` | catalog.read, chat.query, change.read, monitoring.read, knowledge.read, quality.read | 6 | global read; no mutation |
| `developer` | viewer + catalog.execute, change.execute, quality.execute | 9 | active `DEVELOPER` assignments |
| `data_steward` | viewer + catalog.execute/manage, change.execute/manage, quality.execute/manage | 12 | active `DATA_STEWARD` assignments |
| `manager` | steward set + knowledge.manage/review | 14 | either active assignment responsibility |
| `admin` | all application capabilities | 15 | global application read/mutation |

Resource resolution uses one active platform/database/schema System scope. Ambiguous or unresolved
scoped mutation fails closed. Priority is routing metadata, not authority. PHASE 1D sensitivity is
not implemented in this slice.

## Route coverage

The static backend registry contains 49 unique route IDs and the coverage test fails on an unknown,
duplicate or ambiguous named route.

| Methods / path pattern | Class | Capability / boundary | Feature |
|---|---|---|---|
| `GET|HEAD /healthz` | `ANONYMOUS` | exact allowlist | health |
| `GET|HEAD /poc-runtime-config.js` | `ANONYMOUS` | exact allowlist | runtime config |
| `GET|HEAD /auth/login`, `POST /auth/login` | `ANONYMOUS` | exact allowlist | local auth |
| `GET /auth/me`, `POST /auth/logout` | `AUTHENTICATED` | current session/access profile | local auth |
| `GET|PUT /api/v1/change-history/access` | `CAPABILITY_PROTECTED` | `admin.manage` | access admin |
| Change events/list/detail/links/weekly/summary/reverse reads | `CAPABILITY_PROTECTED` | `change.read` + read filtering | Change Management |
| `POST .../cr-link-events` | `CAPABILITY_PROTECTED` | `change.execute` + System | Change Management |
| `POST /api/v1/registration/bulk-preparations/execute` | `INTERNAL_SERVICE` | exact service token only | Airflow callback |
| `GET /poc-api/state/{core,knowledge,governance}` | `CAPABILITY_PROTECTED` | filtered per state/feature | current state |
| `PUT /poc-api/state/{core,knowledge,governance}` | `CAPABILITY_PROTECTED` | bounded key diff/CAS + capability/System | current state |
| `GET /poc-api/capabilities` | `CAPABILITY_PROTECTED` | `monitoring.read` | Monitoring |
| DataHub catalog/tree/facets/dashboard/systems/glossary/asset/lineage/vector reads | `CAPABILITY_PROTECTED` | `catalog.read` + System filtering | Catalog |
| DataHub profile coverage | `CAPABILITY_PROTECTED` | `quality.read` | Quality read seam |
| `POST /poc-api/datahub/manual-metadata` | `CAPABILITY_PROTECTED` | `catalog.manage` + System | Catalog mutation |
| catalog templates/bulk list/candidates/preview | `CAPABILITY_PROTECTED` | `catalog.read` | Registration/Catalog |
| bulk preparation and MinIO upload mutations | `CAPABILITY_PROTECTED` | `catalog.execute` + System | Registration/Catalog |
| `POST /poc-api/llm/chat[/compact|/stream]` | `CAPABILITY_PROTECTED` | `chat.query`; evidence filtered before context | Chat |
| `POST /poc-api/airflow/dags/:id/runs` | `CAPABILITY_PROTECTED` | `admin.manage` | operator/raw provider |
| MinIO accepted-object read | `CAPABILITY_PROTECTED` | `catalog.read` | Registration/Catalog |
| `GET /poc-api/neo4j/graph` | `CAPABILITY_PROTECTED` | `catalog.read` + System filtering | Graph |
| base `/api/v1` or `/poc-api` namespace | `DISABLED` | JSON API boundary | gateway |

Totals: `ANONYMOUS=7`, `AUTHENTICATED=2`, `CAPABILITY_PROTECTED=38`,
`INTERNAL_SERVICE=1`, `DISABLED=1`, `UNKNOWN=0`. The dynamic `state.write` route intentionally
delegates to its bounded key-level capability/CAS policy rather than one blanket capability.

## Product changes

Primary files:

- `frontend/poc-authorization.mjs` and test: central policy, route registry, current System filters,
  bounded core replacement enforcement.
- `frontend/poc-server.mjs` and tests: request-scoped authorization projection, route fences,
  provider/raw gateway controls and server-side filtered reads.
- `frontend/poc-access-document.mjs`, `frontend/poc-state-store.mjs` and tests: additive manager
  vocabulary, current authority projection, ETag/CAS and credential-disable transaction.
- `frontend/poc-disable-local-credential.mjs` and test: operator-only version-guarded disable plus
  session revoke; no public endpoint.
- `frontend/src/App.tsx`, `frontend/src/app/navigation.ts`, layout and POC client/tests: backend
  capability-driven menus/direct-page UX, subject/security-epoch state reset and core ETag use.
- `deploy/poc/Dockerfile.example`, `frontend/package.json`: copy/expose the bounded operator command.

The final lint repair commit removes one unnecessary TypeScript assertion only. No dependency,
package lock, SQL schema, permission table, role table, service or container was added.

## DEV runtime evidence

| Check | Sanitized result |
|---|---|
| Web image | healthy; `linux/amd64`; Node `22.19.0`; OCI revision equals Product SHA |
| image identity | `sha256:d34e104d377d730b17821d5f11c3701e6d1ad04f664e1f4172949ddbecf7ab2a` |
| route registry | 49/49 classified; focused policy test 5/5 |
| anonymous protected API | JSON `401` |
| authenticated unknown API | JSON `404` (unit/runtime role matrix evidence) |
| non-API deep link | intended SPA HTML `200` |
| credential cleanup | enabled 0; active sessions 0 |
| access/runtime roles | admin/viewer/developer/steward/manager projections observed |
| catalog totals | admin/viewer 2002; developer 1000; steward 999; manager 1999 |
| visible Systems | admin/viewer 2; developer 1; steward 1; manager 2 |
| Change events | admin/viewer 46; developer 0; steward/manager 13 |
| Chat General | passed auth fence; external provider returned existing fetch failure |
| Quality/GX | authorization seam only; execution engine not runtime available |

## Security and negative tests

- anonymous protected route `401`; invalid session `401`; inactive subject `403`.
- viewer mutation/access-admin `403`; developer/steward/manager access-admin `403`; admin allowed.
- viewer/developer metadata mutation `403`; steward/manager/admin reached the existing provider
  boundary, which returned its current provider error without a successful mutation claim.
- viewer/developer raw Airflow browser dispatch `403`; exact Airflow service route succeeded, and
  the same service token on a general route returned `401`.
- request header/query/body role, subject or System spoof did not change server authority.
- assigned-System read allowed; other-System event detail was hidden; scoped System rewrite returned
  `403 SYSTEM_SCOPE_SPOOFED` without a core version change.
- two concurrent developer/steward session streams retained distinct subject, role and System sets.
- cookie is `HttpOnly`, `SameSite=Strict`, exact Path and bounded Max-Age; HTTPS requires `Secure`.
  Fixation cookie replacement, logout revocation and expired/revoked rejection passed.
- password reset/session-revoke UI is not implemented yet: `NOT_APPLICABLE_YET` for PHASE 1B and
  retained for PHASE 1C.
- access tokens, session cookies, passwords, hashes and provider credentials are absent from evidence.
- The exact temporary runtime-capture directory containing validation passwords/cookies was deleted
  after the sanitized evidence was finalized; it is not recoverable from the repository.

## Frontend evidence

- Viewer UI showed Search, Change, Quality, Knowledge, Monitoring, Governance and Chat, but no
  Registration or Admin entry; direct `?page=admin` redirected away.
- Admin UI showed Registration and Admin management and survived a hard reload after the Web image
  recreate; the page accurately states the server capability/System contract.
- Manager UI showed Registration, Quality and Knowledge but no Admin menu; its dashboard reflected
  its two assigned Systems.
- Direct API and URL checks prove the backend boundary. Browser local/session storage was not used as
  authority; source and unit tests confirm local client state cannot manufacture capabilities.
- The POC adapter still contains bounded legacy authorship placeholders. They are not authorization
  authority, but final user-specific history/draft isolation remains PHASE 1F.

## Frozen feature regression

One read-only database transaction at the final Product SHA returned:

| Invariant | Result |
|---|---|
| sources | 2; 0 invalid/orphan |
| ledger | 46 rows, 46 event identities, 46 source positions, 0 duplicates |
| CR link events | 4; 0 orphan |
| checkpoints | 2; `51815/52854/1040`, `52849/52942/94`; 0 invalid/orphan |
| Scheduler receipts | 2; versions `[1,1]`; 0 invalid |
| append-only triggers | 2 |

No MCL mutation, checkpoint reset, CR semantic change, PREP mutation or OPS mutation occurred.
Scheduler remains disabled and MCL bindings remain `0/9`; those are current deployment-readiness
findings, not regressions in the frozen runtime capability evidence.

## Final validation commands

The same `50_QUALITY_VALIDATION` session (`gpt-5.6-sol high`, controlled fallback; Antigravity was
not retried) first found one lint blocker, which was repaired in a one-line product commit. The same
session then reran the complete validation from scratch at the final Product SHA:

```text
cd frontend
npm run test:poc-server
# 60/60 PASS

npm test
# 86 files, 586/586 PASS

npm run typecheck
npm run lint
npm run build:poc
# PASS; existing >500 kB chunk warning remains

docker compose --env-file deploy/poc/.env.example \
  -f deploy/poc/docker-compose.poc.yaml config

AIRFLOW_USERNAME=PLACEHOLDER AIRFLOW_PASSWORD=PLACEHOLDER \
POC_AIRFLOW_SERVICE_TOKEN=PLACEHOLDER COMPOSE_PROFILES=airflow \
docker compose --env-file deploy/poc/.env.example \
  -f deploy/poc/docker-compose.poc.yaml \
  -f deploy/poc/docker-compose.airflow.yaml config

git diff --check 8c1f93a456d0fe51e46987b72d66f563f6467d73..e13dbb4f8412937e1d60bd45f83e0e91dc3e91aa
git diff --exit-code 8c1f93a456d0fe51e46987b72d66f563f6467d73..e13dbb4f8412937e1d60bd45f83e0e91dc3e91aa -- frontend/package-lock.json
# PASS
```

Static scans found zero credential/private-key/concrete endpoint/private-IP/conflict-marker/test-
suppression/built-secret findings. The only new absolute URL is the network-free test parser fixture
`https://poc.invalid`. The tracked pre-existing browserless loopback fallback remains backlog.

## Overengineering check

| Item | Result |
|---|---:|
| capabilities | 15 |
| new auth/permission tables | 0 |
| new dependency/package-lock change | 0 |
| new service/container | 0 |
| workspace/OIDC/Keycloak in Node authorization | no |
| generic policy engine/DSL/role hierarchy | no |

## Remaining

- Overall Account/Auth remains `PARTIAL`: PHASE 1C Admin User Management, PHASE 1D sensitivity,
  PHASE 1E legacy retirement and PHASE 1F final multi-account/data isolation acceptance remain.
- Remote-host denial remains `TARGET_RECHECK_REQUIRED`.
- Scheduler/MCL current deployment readiness remains `TARGET_RECHECK_REQUIRED` while disabled and
  unbound; no capture was attempted in PHASE 1B.
- Quality/GX execution and external Chat/vector provider recovery retain their independent backlog.
- Existing Vite chunk-size warning and browserless loopback fallback remain backlog.

Next smallest slice: PHASE 1C minimal Admin User Management only—create a human access user and
credential, edit current role/System/active state, reset password and revoke sessions using the same
access authority. PHASE 1D and later work are not started by this evidence.
