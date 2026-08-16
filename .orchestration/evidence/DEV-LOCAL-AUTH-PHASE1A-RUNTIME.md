# DEV Local Account / Server Session — PHASE 1A runtime evidence

## Scope and lineage

- Product SHA: `618b9713059ba7e31b807ceae3b401766a313668`
- base/published origin/dev: `ef41447a1d470119c1a83280e261d4be411354ef`
- observation completed: `2026-08-16T13:24:05+09:00`
- environment: `DEV_MAC_ARM64`, Web Node `22.19.0`
- Product lineage: four direct commits over origin/dev; no merge, push or PREP/OPS mutation
- fresh Validator: `50_QUALITY_VALIDATION`, controlled fallback `gpt-5.6-sol high` because the
  previously recorded Antigravity path was `agent_unconfigured` and was not retried

The product/security behavior passed fresh validation. The Validator found two stale documentation
claims that still called the POC unauthenticated. They were corrected without changing product code,
then the static documentation gate was repeated.

## Decision and implementation

PHASE 1A-0 was `GO`: the existing access ETag/CAS path, stable `subject_id`, existing PostgreSQL and
the pinned `hash-wasm` Argon2id implementation were sufficient. No principal-type field, workspace,
OIDC, Keycloak, FastAPI authentication runtime, new IAM store or policy engine was required.

| Slice | Result | Evidence |
|---|---|---|
| 1A-0 feasibility/access CAS | `COMPLETE_RUNTIME_VERIFIED` | additive credential/session contract and fixture-preserving bootstrap tests |
| 1A-1 network containment | `COMPLETE_RUNTIME_VERIFIED` | Web and owned support-service host publishes bind to loopback; container peer listener stays internal |
| 1A-2 local authentication | `COMPLETE_RUNTIME_VERIFIED` | Argon2id credential verification, opaque hashed sessions, Origin/CSRF boundary, request-scoped access lookup |
| 1A-3 operator bootstrap/login shell | `COMPLETE_RUNTIME_VERIFIED` | TTY/bounded password-file CLI, no public/default password, direct `/auth/login` assets rooted at `/` |
| overall Account/Auth | `PARTIAL` | capability/System coverage, sensitivity, legacy retirement and full 1F acceptance remain later slices |

## Storage and authority

- `change-history-access-v1` remains the sole role/System/application access authority.
- Credentials store subject reference, normalized login, Argon2id hash and bounded login state only.
- Sessions store SHA-256 token hash, subject reference and lifecycle timestamps only.
- Every protected request reloads the current access document; role/System/inactive state is not a
  session snapshot and the process-global active subject is not request authority.
- The tracked POC SQL change is additive and idempotent: two authentication tables, their constraints,
  FK and indexes. No existing table was renamed/dropped and no migration was squashed.
- Two new DEV human fixtures were created through official access CAS + operator bootstrap. The four
  pre-existing synthetic fixtures received no credential and their stored documents remained exact.
  All validation sessions were revoked; no plaintext password or cookie artifact remains.

## Current runtime observations

| Check | Sanitized result |
|---|---|
| Web | healthy; image OCI revision equals Product SHA; loopback host publish |
| Airflow | healthy; loopback host publish; exact service-token route separated from human session |
| login shell | HTTP 200; `<base href="/">`; referenced root JS/CSS assets HTTP 200 |
| access/core | 6 users/memberships, 2 Systems, 2 assignments; projections agree |
| local credentials | 2; unique login names; 0 credentials for synthetic fixtures |
| local sessions | 4 total, 4 revoked, 0 active |
| MCL | 2 sources, 46 ledger events, 4 CR link events, 2 valid checkpoints |
| checkpoint tuples | first/next/version `51815/52854/1040`, `52849/52942/94` |
| Scheduler receipts | 2 retained, each version 1 |
| current Scheduler/MCL readiness | Scheduler disabled; required MCL bindings configured `0/9` |

The MCL, checkpoint, ledger, link and scheduler rows were queried in one read-only transaction.
No duplicate position, malformed hash, invalid checkpoint, orphan link/ledger row or missing append-only
trigger was found by the fresh Validator.

## Security and negative evidence

- missing/invalid session: `401`
- missing or wrong Origin on cookie-bearing mutation/login: `403`
- inactive mapped user with an existing session: `403`; restoring active state made the same session
  valid without changing its role/System authority
- viewer access to access-admin mutation: `403`
- client subject/role/System spoof headers or query claims: rejected or ignored; server authority unchanged
- unknown authenticated API path: JSON `404`; SPA fallback does not hide API `401/403/404`
- two simultaneous authenticated sessions resolve distinct request-scoped subjects
- logout/revoke removes session authority; backend restart and image recreate preserve durable sessions
- cookie contract: `HttpOnly`, `SameSite=Strict`, exact `Path`; `Secure` required for HTTPS target
- login errors do not distinguish unknown user from wrong password; bounded lock state is enforced
- token, cookie, password, Authorization header and credential hashes are absent from evidence/log output

## Tests at the Product SHA

```text
cd frontend
node --test poc-local-auth.test.mjs poc-server.auth.test.mjs poc-bootstrap-local-user.test.mjs poc-state-store.test.mjs poc-server.test.mjs poc-server.providers.test.mjs
# 64/64 PASS

npm exec -- vitest run --config vitest.config.ts src/App.test.tsx src/poc/PocApp.test.tsx src/poc/pocAuthCompat.test.tsx src/poc/vitePocConfig.test.ts
# 21/21 PASS

npm run lint
npm run typecheck
npm run build:poc
# PASS; existing >500 kB chunk warning remains

uv run pytest -q backend/tests/unit/test_poc_network_containment.py
uv run python -m unittest infra.airflow.tests.test_datariver_auth
uv run ruff check infra/airflow/dags/datariver_auth.py infra/airflow/tests/test_datariver_auth.py
# 2/2 + 2/2 + PASS

docker compose --env-file deploy/poc/.env.example -f deploy/poc/docker-compose.poc.yaml config
AIRFLOW_USERNAME=PLACEHOLDER AIRFLOW_PASSWORD=PLACEHOLDER POC_AIRFLOW_SERVICE_TOKEN=PLACEHOLDER \
  COMPOSE_PROFILES=airflow docker compose --env-file deploy/poc/.env.example \
  -f deploy/poc/docker-compose.poc.yaml -f deploy/poc/docker-compose.airflow.yaml config
# sanitized render PASS

git diff --check ef41447a1d470119c1a83280e261d4be411354ef..618b9713059ba7e31b807ceae3b401766a313668
git diff --exit-code ef41447a1d470119c1a83280e261d4be411354ef..618b9713059ba7e31b807ceae3b401766a313668 -- frontend/package-lock.json
# PASS
```

The fresh Validator independently reran the focused auth/bootstrap/server tests, frontend tests,
network tests, lint, typecheck, package pin/lock comparison, container/image inspection, safe HTTP
probes and aggregate-only PostgreSQL checks. It made no file, runtime or DB mutation.

## Legacy and schema safety

- FastAPI/Keycloak/OIDC/Workspace are not Node POC authentication startup dependencies.
- Existing shared/FastAPI feature code is classified as reusable/historical/future reference, not
  proof of active authentication. No physical deletion occurred.
- The POC frontend still carries a bounded workspace-shaped compatibility profile for the shared UI,
  but it is not present in the backend authorization decision. Retirement is PHASE 1E after the
  replacement path remains accepted.
- The actual DEV POC `public` schema contains eight `poc_*` tables. All are `ACTIVE` or
  `HISTORY_REQUIRED`; none is approved for deletion. The canonical classification and ERD are in
  `docs/06_DATA_MODEL.md`.
- No dependency version or package lock changed. No actual IP, credential, token, fixture identifier
  or password was added to product configuration.

## Remaining risks

- Remote-host negative network probe: `TARGET_RECHECK_REQUIRED`.
- Current Scheduler/MCL config is disabled/unconfigured; this does not invalidate frozen historical
  feature evidence but it prevents immediate capture/catch-up in the current deployment.
- Central capability/System route coverage, raw provider/state capability fencing and route coverage
  gate remain PHASE 1B.
- Full Admin user management is `PARTIAL`; sensitivity, legacy retirement and full multi-account
  feature isolation remain `BACKLOG`.
- No `manager` role was added. The existing four-role authority was not changed.
- The Vite chunk-size warning remains backlog.

G1/G2/G3/G4 are all `NOT_APPROVED`. No publication was performed.
