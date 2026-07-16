# Acceptance report — development/integration baseline

Report date: 2026-07-16 (Asia/Seoul)
Artifact: current local `datariver_v1` branch
Environment: Windows + WSL2 Ubuntu 22.04, Docker Engine 29.6.0, Compose 5.2.0  
Toolchain: Python 3.12.12, uv 0.9.17, Node.js 22.19.0, npm 10.9.3  
Decision: **development and local integration baseline accepted; production release not accepted**

This report supersedes the source-only report and the runtime-open statements in the 2026-07-14 independent reviews. It records repeatable evidence from the current working tree, not a signed release artifact or production environment.

P0–P3 foundation addendum, updated 2026-07-16: current source checks additionally include the stable DataHub v1.6.0 release contract and typed OIDC assurance. Hardware WebAuthn requires an exact approved ACR+AMR combination and `auth_time`; OTP, generic MFA and refreshed-token `iat` cannot satisfy high-risk authorization. Browser remediation is bounded to typed authentication actions, rejects unsafe return locations, and never automatically replays a denied mutation after an authentication redirect. Compatibility migrations and the current hybrid runtime have separate live evidence below.

## Source and build evidence

| Gate | Result | Executed evidence |
|---|---|---|
| Python format/lint | PASS | Ruff format and check across backend, tests, DAGs, migrations and static-verification scripts |
| Python type safety | PASS | strict mypy: 121 source files, zero issues |
| Backend behavior | PASS | 307 pytest tests: prior identity, governance, retention, RLS, search/DataHub, KG, sharing and evidence gates plus governed classification access/provider/grant administration, disabled-first inference contracts, bounded DB-pool metrics and the PgBouncer probe source contract |
| Frontend | PASS | TypeScript build mode, ESLint zero warnings, 9 test files/31 tests including classification-policy, provider-profile and RESTRICTED-grant Admin states and mutation contracts |
| Frontend artifact | PASS | current source build: JS 377.75 kB / gzip 107.56 kB; CSS 9.99 kB / gzip 3.08 kB |
| Dependency audit | PASS | `pip-audit 2.10.0`: no known runtime vulnerabilities; `npm audit`: 0 vulnerabilities |
| Repository/IaC scan | PASS | Trivy 0.70.0 `vuln,secret,misconfig`, HIGH/CRITICAL, ignored-unfixed: zero findings after making the Keycloak non-root user explicit |
| Migration | PASS | current generated `0001` SHA-256 `295efc02404c8c9d27d6de8eca8f1b2ddc9e4dd60570ae6bbe0b3bfedf2daf1d`; Alembic sole head `0011` upgraded the populated local database and is the packaged/runtime readiness revision |
| Assistant inference contract | PASS (source/unit only) | typed authorized package/result has no SQL, Cypher, arbitrary HTTP, tool or mutation fields; invalid/unavailable output refuses to `검증 불가`; no adapter, endpoint, secret, durable job or provider call is wired |
| PgBouncer RLS gate | PASS (source/unit only) | the probe validates passwordless URLs, file secrets, transaction mode, single-server reuse and fail-closed workspace fixtures; PgBouncer is not deployed and no live pooler result is claimed |
| Static invariants | PASS | Compose dependencies/secrets, DataHub release and identity-assurance contracts, runtime hardening, architecture imports, least-privilege DB roles, tenant foreign keys, seed determinism and documentation links |
| Scripts/config | PASS | POSIX/Bash/PowerShell parsing and base, identity, Airflow, gateway and combined Compose interpolation |
| Reference preservation | PASS | 424 files / 4,763,143 bytes; zero missing, byte or SHA-256 mismatches; secret/cache exclusions verified |
| Independent review | PASS WITH PRODUCTION GATES | Data Architect and Data Engineer/SRE reviews are retained under `docs/reviews/` with post-review status notes |

The optional seed produced the stable logical hash `df039426579bc369f8fda8f6154005c500860ab2ab5a9e263928ef1508b0ebc9`: 12 catalog assets, 257 nodes and 279 edges. Apply, independent verify, remove and re-apply all succeeded.

## Current hybrid-development runtime evidence

The normalized v1 topology keeps PostgreSQL, cache/queue Valkey, SeaweedFS, Keycloak and APISIX in
containers. Uvicorn, the outbox relay, three workers and Vite run directly from the Windows source
tree. The separately operated DataHub core is reused and remains outside DataRiver lifecycle
ownership.

| Gate | Result | Evidence |
|---|---|---|
| Runtime routes | PASS | direct API live/ready, APISIX live and Vite-to-APISIX API proxy returned 200 |
| External DataHub | PASS (local integration) | GMS health and scoped-token GraphQL authentication succeeded; DataRiver did not start or migrate DataHub |
| Migration `0003` | PASS | populated `0002` database upgraded; watermark table has forced RLS, app `SELECT/INSERT/UPDATE` only and obsolete timestamp index is absent |
| Migration/readiness `0004` | PASS | app role received only version-table read access; direct API readiness requires the packaged sole head while liveness remains independent |
| Immutable evidence `0005` | PASS | populated database upgraded in place; citation columns/checks/unique rank and chunk constraints are present, forced RLS remains enabled and the app role has only `SELECT/INSERT`; direct `UPDATE/DELETE` were denied |
| Retention safety `0006` | PASS | populated database upgraded in place; relay pruning API/call path is absent, `datariver_relay` has zero table `DELETE` privileges, and automatic retention reports `DISABLED_NOT_READY` until governed WORM/Legal-Hold/Maker-Checker gates exist |
| Governed administrator access `0007` | PASS (backend/local DB) | typed direct and Maker-Checker APIs, exact assurance matrix, five-minute/hash/version/one-time invariants and minimal outbox events passed; clean and upgraded DB fingerprints matched for columns, constraints, indexes, RLS policies and grants; app-role protected-column/approval update and workflow DELETE were denied. The local workspace has only one eligible human security administrator, so fallback correctly remains disabled until a real second administrator and two-user browser journey exist |
| Retention governance `0008` | PASS (backend/local DB) | versioned policy proposal/independent decision and immediate Legal Hold placement/release Maker-Checker APIs passed with optimistic concurrency, idempotency and integrity hashes. Forced RLS, least-privilege column grants and append-only hold events were verified from both clean and upgraded databases. All automated deletion and erasure execution remain explicitly `DISABLED_NOT_READY`; no destructive endpoint exists |
| Erasure review `0009` | PASS (backend/local DB) | typed request/independent decision APIs bind the canonical target snapshot and active policy ID/hash, recheck applicable Legal Holds and expose no execution capability. Clean and upgraded schema fingerprints matched; cross-workspace/empty-context access, immutable-column and event mutation, stale version, duplicate payload, altered policy hash and expired approval were denied. Expired rejection remained available to close stale reviews. The populated local database upgraded in place and API/Gateway readiness returned 200 after the host source processes restarted |
| Immutable archive evidence `0010` | PASS (backend/local DB) | clean and historical migrations produced the same archive schema; capability and receipt rows are forced-RLS append-only evidence with app-role read-only grants. Exact policy/configuration/encryption/runtime-principal composite bindings, provider/full-readback checksum equality, retention read-back, literal-null version, raw Chat source and no-cascade negatives passed. No archive/export/deletion worker or target WORM claim was enabled |
| Governed classification access `0011` | PASS (backend/local DB) | four immutable policy rules, authorization/provider generations, active-policy-bound RESTRICTED grants with append-only events, and immutable inference profile versions passed forced-RLS, least-privilege, maker-checker, revocation and generation checks. Admin API/FE contracts are implemented; no external inference execution was enabled |
| Concurrent watermark | PASS | two app-role sessions advancing one workspace returned generations `[1, 2]`; rollback preserved `2`; a cross-workspace advance was denied by RLS |
| Seed generation | PASS | migration backfill `1`, remove `2`, re-apply `3`; verify was a no-op; final counts remained 12 assets/257 nodes/279 edges |
| Authorized search | PASS | same-token semiconductor `wafer` search returned the two expected authorized assets after API source reload |
| Same-token policy revocation | PASS (local direct API) | 100 iterations/scenario: inactive membership p99 100.660 ms, explicit search deny p99 167.743 ms, system/domain scope removal p99 193.388 ms; original Airflow membership restored and verified. APISIX correctly rate-limited the first high-rate attempt, so cache-policy timing was rerun directly on `:8000` |
| Local interactive OIDC assurance | PASS (flow/probe) | existing Keycloak realm migrated and re-read with no drift; an ephemeral browser-flow probe received a LoA 1 token carrying `acr=1`, `amr=pwd` and `auth_time`, and a WebAuthn-required page for LoA 2, then removed the probe user; zero probe users remained. A real USB key ceremony and hardware-token/backend journey remain a target-environment gate |

## Live Compose evidence (pre-P0-hardening runtime baseline)

The combined core + Keycloak + Airflow + APISIX stack was built and started as Compose project `datariver-next`. Local verification used alternate host ports `18080`, `18081` and `19080` because the preserved legacy stack already occupied the defaults. Clean clones retain documented defaults `8080`, `8081` and `9080`.

| Gate | Result | Evidence |
|---|---|---|
| Stack state | PASS | 16 long-running services up; every defined health check healthy; migration, object-storage init and Airflow init exited 0 |
| Runtime hardening | PASS | API, web, Keycloak and APISIX ran non-root with read-only root filesystems and `no-new-privileges`; generated/temp state used bounded tmpfs or named volumes |
| Core HTTP | PASS | direct API readiness 200, web health 200, web-to-API proxy 200, APISIX-to-API health 200 |
| Web headers | PASS | CSP present, `X-Frame-Options: DENY`, content-type/referrer/permissions headers present |
| OIDC | PASS | Keycloak discovery issuer matched `http://localhost:8081/realms/datariver`; client-credentials token had expected issuer, audience and service subject |
| Gateway enforcement | PASS | protected catalog without token 401; valid service token 200 with 12 permitted assets and an APISIX request ID |
| PostgreSQL migration | PASS | deterministic initial migration applied to PostgreSQL 17.10 without error |
| RLS isolation | PASS | application role observed 0 rows with no workspace context, 12 in the seed workspace and 0 in another workspace |
| Least privilege | PASS | application-role direct catalog `DELETE` was denied |
| Airflow | PASS | metadata DB, scheduler, triggerer and DAG processor healthy; `datariver_catalog_probe` and `datariver_catalog_sync` registered paused; import errors `[]` |
| Seed runtime | PASS | apply/verify/remove/re-apply completed against the live database with expected hash/counts and scoped service membership |
| Runtime logs | PASS | 12 application/edge/worker services scanned over the final 15-minute window; zero traceback, fatal, panic or error-severity patterns |

## Recovery and degradation evidence

| Scenario | Result | Observed behavior |
|---|---|---|
| Cache Valkey stopped | PASS | API readiness remained 200 and authorized catalog search still returned 12 correct rows |
| Cache Valkey restarted | PASS | container returned to healthy without application restart |
| API process restart | PASS | APISIX returned to readiness automatically after the transient outage |
| API container replacement | PASS | web and APISIX both returned 200 while the web container ID stayed unchanged; Nginx now re-resolves Docker DNS and retained no stale upstream IP |
| Outbox relay restart | PASS | relay returned to running state; no fatal loop appeared in final logs |
| APISIX read-only startup | PASS | generated Nginx configuration and temp paths use non-executable tmpfs; real proxied HTTP health check passed |
| Airflow cold start | PASS | API became healthy under the 90-second startup grace configured for modest developer hosts |

## Repeatable source gate

```bash
uv sync --frozen --all-extras
uv run ruff format --check backend/src backend/tests infra/airflow/dags \
  scripts/generate_initial_migration.py scripts/probe_policy_revocation.py scripts/verify_static.py
uv run ruff check backend/src backend/tests infra/airflow/dags \
  scripts/generate_initial_migration.py scripts/verify_static.py
uv run mypy backend/src backend/tests
uv run pytest backend/tests -q
uv run python scripts/verify_static.py
uv run python scripts/generate_initial_migration.py

cd frontend
npm ci
npm run typecheck
npm run lint
npm run test -- --run
npm run build
npm audit --audit-level=high
```

On the reviewed Windows/UNC workspace, Vitest was executed on a temporary `pushd` drive with `--pool=threads --maxWorkers=1 --no-file-parallelism`; this changes only local execution parallelism. Linux CI uses the canonical npm commands above.

## Remaining production acceptance gates

These items are not source defects, but they prevent a production-readiness claim:

1. Execute DataHub search/detail/sync/change apply/re-read contract tests against the target deployed DataHub version and production-like credential. Local health and GraphQL authentication passed against the separately operated development DataHub, but this is not the target contract gate.
2. Complete real multipart/CORS/copy/checksum/lifecycle tests against the target object-storage deployment and a PostgreSQL + object consistency backup/restore drill with measured RPO/RTO.
3. Run the full ABAC matrix with two real OIDC user identities, browser PKCE/password reset/hardware-WebAuthn step-up journeys, policy revocation timing, password-fallback maker-checker consumption, Legal Hold release, erasure review and audited enterprise subject/workspace administration.
4. Replace Airflow `SimpleAuthManager`, which is deliberately local-development only, with the environment's supported enterprise/FAB SSO configuration before any non-local exposure.
5. Run browser E2E, 60-minute target load/soak, queue saturation, worker kill/reclaim, DataHub fault injection and projection rebuild/chaos tests on the reference deployment shape. External inference additionally requires pre/post-call live policy/profile/attestation revalidation, durable queue/idempotency, SSE timing/cancellation, provider metrics and scaled red-team evidence.
6. Execute backend/frontend and all promoted overlay image scans in an isolated CI/release runner, retain CycloneDX SBOM and license reports, and promote digest-pinned images. Local repository/IaC scanning passed; a Docker socket was intentionally not mounted into a third-party scanner container.
7. Produce a clean-clone CI run tied to a commit SHA, immutable image digests, target-environment evidence and accountable reviewer sign-off with exception expiry.

## Conclusion

No known formatter, linter, type, unit, frontend-build, migration-graph or static-architecture error remains in the current source. The hybrid runtime, compatibility migrations through `0011`, local RLS/gateway/seed and post-hardening API smoke checks passed. The project is suitable for Git sharing and continued environment integration. Production release remains blocked by the target-system, scale/load, recovery, browser, HA, external-inference and signed supply-chain gates listed above.
