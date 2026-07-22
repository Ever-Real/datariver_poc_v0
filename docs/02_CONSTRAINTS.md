# Constraints and technology policy

## Hard constraints

- External DataHub already exists and is integrated through a version-aware anti-corruption layer.
- Production authentication is OIDC; DataRiver never stores user passwords. An optional governed
  Keycloak adapter may relay a temporary credential directly to Keycloak, but never persists,
  hashes, audits or returns it.
- PostgreSQL is the only required canonical application database.
- Cache, queues, graph projections, metrics and orchestrator state are never business truth.
- No proprietary/paid-only feature is required for correctness, security, backup, or scaling.
- Seed and demo data are disabled by default.
- All secrets enter by secret mount or environment bootstrap and databases store only `secret_ref`.
- All deployable images are exact-tag pinned; production promotion records digests.

## Approved default stack

Reviewed 2026-07-14 against official project documentation/repositories.

| Capability | Default | License | Decision |
|---|---|---|---|
| API | FastAPI/Pydantic | MIT | typed async HTTP boundary |
| UI | React/TypeScript | MIT | mature modular web stack |
| canonical DB/vector/search | PostgreSQL/pgvector/`pg_trgm` | PostgreSQL/PostgreSQL | durable workflow, RLS, JSONB, vector and initial authorized read plane |
| graph projection | PostgreSQL adjacency by default; Apache AGE optional | PostgreSQL/Apache-2.0 | canonical KG remains normal tables; AGE is replaceable |
| cache | Valkey 9.1.x | BSD-3-Clause | active, open caching; strict memory cap |
| job delivery | separate Valkey + worker | BSD-3-Clause/application licenses | never shares cache eviction policy |
| batch orchestration | Apache Airflow 3.3.x | Apache-2.0 | scheduled/bulk/reconciliation only |
| object API | SeaweedFS 4.39 S3 | Apache-2.0 | active S3-compatible default, conformance tested |
| authorization policy | embedded typed ABAC; OPA adapter/profile | Apache-2.0 for OPA | app remains enforcement point |
| identity | external OIDC; Keycloak local profile | Apache-2.0 | no application passwords |
| telemetry | OpenTelemetry Collector, Prometheus, Grafana, Alertmanager, Tempo, Loki | component-specific review | opt-in vendor-neutral signal boundary |
| gateway | Apache APISIX profile | Apache-2.0 | auth/routing/coarse quota; app ABAC remains |

## Restricted alternatives

- MinIO is not the new default: its official repository is archived/read-only as of 2026-04-25 and the community distribution/license posture no longer meets the continuing-maintenance preference. Existing S3/MinIO endpoints remain possible through the S3 port after conformance testing.
- Neo4j Community is an optional compatibility/read-projection profile only. Correctness cannot depend on clustering, online backup, or fine-grained authorization available only outside Community. Bolt is never public.
- Grafana, Tempo and Loki remain opt-in observability components because their distribution/license posture needs an explicit review. The `aux-compose.yml` Pilot overlay is not a production acceptance shortcut.
- A message broker may replace Valkey delivery when throughput/retention warrants it, but canonical outbox/inbox semantics may not change.

## Dependency policy

Allowed licenses for unattended inclusion: Apache-2.0, MIT, BSD-2/3-Clause, PostgreSQL, ISC. MPL/LGPL/GPL/AGPL or source-available dependencies require a recorded legal/distribution decision. Unknown licenses fail CI. Dependencies and images require SBOM, vulnerability scan, and a maintenance review at every release.

## Resource budgets for development PC

| Profile | Target memory |
|---|---:|
| core app + PostgreSQL + two Valkey instances | <= 4 GiB |
| identity/policy/gateway | additional <= 2 GiB |
| Airflow | additional <= 3 GiB |
| observability | additional <= 2 GiB |
| optional graph projection | additional <= 2 GiB |

Profiles must be independently selectable. Resource limits are validated in Compose and tuned from measured data rather than silently removed.

## Data and API limits

- default/max page size: 25/100;
- cache entry: <= 1 MiB, every key TTL-bound;
- request JSON: <= 2 MiB unless endpoint explicitly documents less;
- file content bypasses API memory by presigned multipart upload;
- presigned URL lifetime: <= 15 minutes;
- arbitrary SQL, Cypher, GraphQL forwarding, shell commands, and unbounded graph traversal are prohibited;
- public analysis queries are registered typed templates with row, hop, cost and timeout bounds.

## References

- Valkey: https://github.com/valkey-io/valkey
- Apache Airflow: https://airflow.apache.org/docs/apache-airflow/stable/
- SeaweedFS: https://github.com/seaweedfs/seaweedfs
- Apache AGE: https://age.apache.org/
- MinIO maintenance state: https://github.com/minio/minio
