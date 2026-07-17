# Test and stabilization strategy

## Latest executed baseline

The current development/integration baseline passes 429 backend tests, strict mypy over 191 source/test files, Ruff formatting/lint, TypeScript/ESLint/build, deterministic migration generation and static architecture/Compose/role/readiness checks. The last complete frontend baseline remains 18 files/75 tests; for this change the modified registration workbench file passed 6/6 tests, while repeated whole-suite runs on the Windows WSL network drive reached their bounded timeout without an assertion result. The frontend build emits JS 479.89 kB (gzip 137.78 kB) and CSS 38.74 kB (gzip 7.87 kB). The live hybrid-development baseline also passed PostgreSQL RLS, Keycloak service-token OIDC, schema-aware API/APISIX readiness, Vite-to-APISIX proxying, DataHub GraphQL authentication and semiconductor seed verification. The current source additionally serves immutable server-owned governance target bindings and a typed MANUAL dataset-description preview/create contract through APISIX; raw Aspect entry points require a separately granted hardware-human action and have no ordinary browser form. BULK upload/validation uses attempt-scoped promotion, full promoted-byte SHA-256 read-back and a commit receipt before source cleanup. Migration `0016` installs forced-RLS preparation job/receipt/candidate/binding evidence, and the API can now select a bounded typed profile and queue/read an exact accepted-evidence preparation. A source-only bounded parser enforces the V1 byte/CSV/identity/hash contract, while its runtime worker, candidate API and typed proposal execution remain disabled. The earlier container baseline additionally passed Airflow DAG imports, optional seed remove and repository/IaC Trivy scanning. Exact commands and the distinction between current source and earlier evidence are in [the acceptance report](12_ACCEPTANCE_REPORT.md).

Executed resilience checks included cache-Valkey stop/recovery, API process restart, API container replacement behind both Nginx and APISIX, and outbox-relay restart. The API replacement test deliberately kept the web container running and verified that its Docker DNS resolver did not retain a stale upstream address.

The local seeded same-token revocation probe ran 100 iterations per scenario against the direct API:
membership inactive p99 100.660 ms, explicit `catalog.search` deny p99 167.743 ms and system/domain
scope removal p99 193.388 ms. All passed the provisional 60-second SLA and the original service
membership was restored. This is development evidence, not the required target-load/two-identity or
already-open Chat/SSE gate.

The strategy below remains the production release matrix. Target DataHub/object storage, backup/restore, browser PKCE/hardware-WebAuthn and governed password fallback, load/soak, queue saturation, worker crash-at-each-boundary and promoted-image scans are still environment gates rather than silently assumed passes.

## Test pyramid and gates

| Layer | Tools/approach | Required evidence |
|---|---|---|
| Domain unit | pytest, pure TypeScript tests | state transitions, policy rules, graph validation |
| Architecture | import graph/AST tests | domain/application contain no adapter imports; contexts do not write across schemas |
| Repository/integration | PostgreSQL/Testcontainers | constraints, RLS, migrations, outbox atomicity, idempotency |
| Contract | OpenAPI snapshot, DataHub/S3/OIDC/OPA fixtures, Schemathesis | provider error mapping and API compatibility |
| UI component | Vitest/Testing Library | loading/error/permission/accessibility behavior |
| Browser E2E | Playwright | search, upload/dry-run, CR lifecycle, monitoring, KG release, Chat |
| Resilience | Toxiproxy/process kill | dependency failure matrix and recovery |
| Performance | k6 plus RSS/DB/Valkey metrics | p95, error rate, memory and soak stability |
| Security/supply chain | pip-audit, npm audit, Trivy secret/vulnerability/IaC/image scan, CycloneDX, license allowlist | zero unresolved Critical/High, retained SBOM |

Retention negative tests must prove that the relay exposes no pruning operation and has no `DELETE` privilege. Future retention automation is not accepted until dependency failure, missing approval, active Legal Hold, WORM retention read-back mismatch and replay/concurrency cases all produce zero deletions.
| Recovery | isolated restore/rebuild scripts | PostgreSQL restore and graph projection deterministic hash |

The source-level identity suite additionally checks same-origin return-state validation, explicit
WebAuthn AIA and LoA request arguments, missing/ambiguous ACR fail-closed behavior, bounded problem
remediation and exactly one HTTP attempt for a denied mutation. The backend administrator suite
checks the exact password/hardware assurance matrix, default-disabled fallback, maker/checker/target
separation, five-minute expiry, canonical hash and versions, eligibility revocation, two-admin
invariant, idempotent one-time consume, minimal outbox data, forced RLS and column-level grants.
Browser E2E must still prove a real security-key ceremony, `max_age=0` password reauthentication
with two real users, no password field or direct bypass in the page, and explicit resubmission after
returning from authentication.

The source-level inference suite checks that the package and provider draft contain no SQL, Cypher,
HTTP, tool or mutation fields; RESTRICTED and cross-workspace evidence is rejected; policy/profile
hashes, jurisdiction, classification ceiling and both attestations are bound; unavailable or invalid
provider output becomes `검증 불가`; and citations are a bounded, duplicate-free subset of the exact
authorized chunks. This is contract evidence only. External enablement still requires pre-call and
post-call live policy/profile/attestation revalidation, durable delivery/idempotency, SSE timing and
cancellation tests, provider metrics and the scaled red-team corpus.

## Core correctness scenarios

- State machine rejects every undeclared transition and stale aggregate version.
- Requester cannot final-approve; required multi-approval actors are distinct.
- `APPLY_QUEUED` and outbox insert are one transaction.
- Duplicate event and duplicate idempotency key produce one business effect.
- DataHub failure/mismatch never produces `APPLIED`; reconcile retry can recover.
- Catalog writes cannot bypass governance.
- Every graph publish assertion has provenance and passes ontology/reference checks.
- Release content is immutable; same release rebuild has identical hash/count and golden-query output.
- Chat citations are a non-empty, duplicate-free subset of the exact currently authorized immutable chunks; workspace/chunk/content hash is revalidated and invalid output becomes `검증 불가` with no persisted citation.

## Authorization matrix

For each route, test no token, invalid issuer/audience/algorithm, inactive subject, missing workspace membership, workspace mismatch, insufficient clearance/system/domain, lifecycle restriction, positive allow, explicit deny, policy-service outage, changed policy with stale cache and protected-field redaction. List, facet, suggestion, count, download, export and SSE receive the same coverage as detail endpoints.

## Failure injection

| Fault | Pass condition |
|---|---|
| DataHub unavailable/rate-limited/contract drift | bounded stale or classified 503; durable pending work; no false complete; fixed-label request/circuit metrics |
| DataHub concurrency saturated | bounded queue timeout and classified `OVERLOADED`; bulkhead rejection metric increments |
| cache unavailable/evicted | correct uncached response, no secret leakage |
| API container replaced | Nginx/APISIX re-resolve service DNS; no dependent restart or persistent 502 |
| queue unavailable | outbox age grows; automatic replay after recovery |
| worker killed before/after external call | idempotent resume and reconcile, no duplicate result |
| PostgreSQL unavailable | writes fail 503 and no message is published |
| object store/multipart interruption | upload recover/abort; orphan reconciliation works |
| policy unavailable | protected operations fail closed |
| graph unavailable/drift | catalog works; projection rebuild restores hash |
| LLM unavailable/malicious response | authorized evidence remains; no mutation/query execution |
| poison event | bounded retry to DLQ; audited operator replay |

## Memory and performance

- Stream synthetic 500 MiB and 1 GiB objects; API RSS increase <= 64 MiB.
- Cap list results at 100 and cache value at 1 MiB.
- Run target load for 60 minutes; after warm-up API RSS stays within ±10% absent explained cache bounds.
- Reference-host targets: cached search p95 <= 300 ms, uncached <= 800 ms, CR write <= 400 ms, error rate < 1%.
- Queue eviction count stays zero; cache respects maxmemory and TTL.
- Test ABAC-aware pagination/facets at realistic permitted/denied ratios.
- Reuse a search cursor only with its exact workspace, permission scope, policy/generation, projection version, query, filters and page size; stale or cross-shape cursors must fail explicitly.
- Prove multi-term search uses ALL semantics while `%`, `_` and backslash remain literal data, and render only client-escaped highlights from server plain-text match fragments.
- Expand Resource Tree branches one page at a time; no browser test may preload the catalog to synthesize hierarchy or count hidden rows.
- Filter every lineage node and intermediary as a set through the catalog authorization predicate; a denied intermediary must truncate the path and must never be bypassed to connect two visible endpoints.

## Migration and portability

- Empty DB upgrades to one Alembic head and matches declared metadata.
- Previous release DB upgrades and rolls application forward without data loss.
- Clean clone on Windows/WSL2, Linux and macOS follows one documented Compose path.
- No absolute path, committed secret, volume, upload, test artifact or seed appears in a clean production checkout.

### PgBouncer pre-adoption RLS gate

PgBouncer must not become an API database path until transaction-local workspace and subject context
has passed `scripts/probe_pgbouncer_rls.py`. Run the probe only against an isolated integration
database with at least one catalog fixture in each of two distinct workspaces. Its separate admin
connection verifies transaction mode and `default_pool_size=1`; the application connection then
forces reuse of one PostgreSQL server connection across commit, rollback and database-error paths,
checks an interrupted transaction, and proves both context reset and cross-workspace row denial.

The URLs must not contain passwords and every secret must be a `file:` reference. The command has no
portable endpoint, identity or workspace defaults; the deployment supplies all six values. A missing
fixture, a non-reused server connection or an unavailable PgBouncer admin console is inconclusive and
therefore fails the gate. This probe is a prerequisite, not evidence that PgBouncer, a connection
budget or a target `max_connections` value has been accepted for production.

## Release gate

CI success alone is insufficient. The acceptance report records commit/image digest, environment, dataset, commands, machine-readable reports, reviewer, exceptions and expiry. Image scanners run only in an isolated CI/release runner; never grant a third-party scanner a developer Docker socket merely to produce local evidence. Release is blocked by failed functional/ABAC/migration/recovery gates or unresolved Critical/High security findings. Performance variance is a documented block unless the acceptance owner approves a time-bounded exception with mitigation.
