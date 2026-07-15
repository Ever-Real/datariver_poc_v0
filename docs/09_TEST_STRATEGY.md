# Test and stabilization strategy

## Latest executed baseline

The 2026-07-15 development/integration baseline plus the current P0 source hardening passed 76 backend tests, strict mypy over 110 source files, Ruff formatting/lint, 6 frontend tests, TypeScript/ESLint/build, deterministic migration generation and static architecture/Compose/role checks. The live hybrid-development baseline also passed PostgreSQL RLS, Keycloak service-token OIDC, APISIX-to-host-API routing, Vite-to-APISIX proxying, DataHub GraphQL authentication and semiconductor seed verification. The earlier container baseline additionally passed Airflow DAG imports, optional seed remove and repository/IaC Trivy scanning. Exact commands and the distinction between current source and earlier evidence are in [the acceptance report](12_ACCEPTANCE_REPORT.md).

Executed resilience checks included cache-Valkey stop/recovery, API process restart, API container replacement behind both Nginx and APISIX, and outbox-relay restart. The API replacement test deliberately kept the web container running and verified that its Docker DNS resolver did not retain a stale upstream address.

The strategy below remains the production release matrix. Target DataHub/object storage, backup/restore, browser PKCE/TOTP, load/soak, queue saturation, worker crash-at-each-boundary and promoted-image scans are still environment gates rather than silently assumed passes.

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
| Recovery | isolated restore/rebuild scripts | PostgreSQL restore and graph projection deterministic hash |

## Core correctness scenarios

- State machine rejects every undeclared transition and stale aggregate version.
- Requester cannot final-approve; required multi-approval actors are distinct.
- `APPLY_QUEUED` and outbox insert are one transaction.
- Duplicate event and duplicate idempotency key produce one business effect.
- DataHub failure/mismatch never produces `APPLIED`; reconcile retry can recover.
- Catalog writes cannot bypass governance.
- Every graph publish assertion has provenance and passes ontology/reference checks.
- Release content is immutable; same release rebuild has identical hash/count and golden-query output.
- Chat citations are a subset of currently authorized resources and name source/release version.

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

## Migration and portability

- Empty DB upgrades to one Alembic head and matches declared metadata.
- Previous release DB upgrades and rolls application forward without data loss.
- Clean clone on Windows/WSL2, Linux and macOS follows one documented Compose path.
- No absolute path, committed secret, volume, upload, test artifact or seed appears in a clean production checkout.

## Release gate

CI success alone is insufficient. The acceptance report records commit/image digest, environment, dataset, commands, machine-readable reports, reviewer, exceptions and expiry. Image scanners run only in an isolated CI/release runner; never grant a third-party scanner a developer Docker socket merely to produce local evidence. Release is blocked by failed functional/ABAC/migration/recovery gates or unresolved Critical/High security findings. Performance variance is a documented block unless the acceptance owner approves a time-bounded exception with mitigation.
