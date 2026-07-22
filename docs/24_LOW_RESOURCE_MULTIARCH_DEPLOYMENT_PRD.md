# Low-resource multi-architecture deployment PRD

## 1. Outcome and scope

This plan establishes a repeatable DataRiver **Single-node Pilot** on two container architectures:

| Host | Docker report | OCI release platform | Intended placement |
|---|---|---|---|
| Mac Mini development PC | `linux/aarch64` | `linux/arm64` | DataRiver development, local Keycloak/PostgreSQL, external Redis/MinIO/DataHub, native Ollama |
| Windows WSL preparation PC | `linux/x86_64` | `linux/amd64` | DataRiver candidate, local PostgreSQL/Keycloak, separately operated Redis/Neo4j/APISIX, external MinIO/DataHub/Airflow/telemetry/LLM |

The goal is identical source and configuration contracts with architecture-specific images. The
preparation PC is not a production or HA environment. Production promotion and HA acceptance remain
separate target-environment gates.

## 2. Dependency classification

“Container required” and “capability required” are different questions. The platform process can
start with a smaller set, while a feature must fail closed or report unavailable when its connector
is absent.

The table is the target dependency contract. At the current baseline the API still validates
DataHub, Redis and S3 settings and secret references during startup even when a feature is not used.
That mismatch is tracked as an implementation gate; until capability guards/no-op adapters exist,
operators must provide valid external connector configuration and must not claim that
PostgreSQL/OIDC alone is an implemented minimal runtime.

| Component | Base ownership | Requirement |
|---|---|---|
| DataRiver migrate/API/web | DataRiver | bootstrap core |
| PostgreSQL | DataRiver pilot | canonical bootstrap core |
| Keycloak | optional DataRiver overlay | required only when no approved external OIDC provider exists |
| outbox relay | DataRiver | integration core when side effects are enabled |
| Redis cache + delivery | external | cache degradation is tolerated; delivery is required for asynchronous worker features |
| S3/MinIO | external | required for registration upload, accepted files and catalog exports; not required for read-only catalog search |
| DataHub | external | required for fresh ingestion, provider detail and governed metadata application; local projection may remain read-only during outage |
| upload/validation/export workers | optional DataRiver processes | start only for the corresponding storage capability |
| Neo4j | external optional projection | required only for enabled knowledge graph projection/query |
| LLM/embedding/reranker | external optional | required only for enabled Chat/knowledge features |
| Airflow | external optional | scheduling convenience; never canonical business state |
| APISIX | external/edge optional | ingress policy and routing; not an application bootstrap dependency |
| Prometheus/Grafana/OTel and stores | external optional | operational evidence; absence does not authorize an HA claim |

## 3. Product requirements

- `MA-DEP-001`: normalize Docker aliases `aarch64→arm64` and `x86_64→amd64`; reject every other
  platform unless a new reviewed contract is added.
- `MA-DEP-002`: produce separate arm64/amd64 artifacts from one clean Git commit and a common
  release inventory. Record architecture-specific IDs/digests and checksums.
- `MA-DEP-003`: inject browser-safe OIDC/API configuration at container start. No build-host URL
  may be embedded as the deployment source of truth.
- `MA-DEP-004`: export an exact-commit source bundle and verify it independently of image tars.
- `MA-DEP-005`: target import must perform hash, platform, commit, image inventory and Compose
  no-build/no-pull checks before migration.
- `CFG-001`: select exactly one ignored environment file per host. Literal credentials are
  forbidden; secret file references and a separately transferred `secrets/` directory are used.
- `CFG-002`: database System Settings startup activation stays disabled in these profiles. Its
  development inventory/probe history may remain visible.
- `CONN-001`: separately composed local connectors share a named external network. Remote endpoints
  use private DNS/TLS and must not rely on loopback.
- `CONN-002`: Redis cache and delivery use distinct service origins; S3 endpoints are
  credential-free origins; an external development Neo4j hostname must be explicitly allowlisted.
- `DATA-001`: never copy Docker volumes across architectures. PostgreSQL uses logical backup/restore;
  S3 objects use key/size/SHA-256 reconciliation; Redis cache is rebuilt.

## 4. Browser and low-resource requirements

- `LOW-MEM-001`: catalog page choices are 25, 50 and 100 only. One page action issues one bounded
  asset request; the browser never crawls cursor pages to emulate 200/500/1000/all.
- `LOW-MEM-002`: selecting an authorized tree or lineage asset opens detail independently and does
  not scan the current search from page one.
- `LOW-MEM-003`: facets are refreshed only when query, filters or authorization scope changes, not
  on cursor navigation.
- `LOW-MEM-004`: retain at most eight expanded tree branches with at most 200 nodes per branch;
  abort evicted/collapsed in-flight branch requests, retain at most 1,000 unique provider schema
  fields per asset, and serialize detail fields in server pages of at most 200 fields (100 by
  default) with explicit total/total-exact/available/truncated metadata. A truncated provider
  response reports a bounded `1,001+` lower bound instead of allocating an unbounded uniqueness set.
- `LOW-MEM-005`: CSV stays streaming. XLSX is disabled or capped for the low-resource profile until
  a measured write-only/spooled implementation meets its worker RSS budget.
- `LOW-MEM-006`: the frontend production bundle uses route/feature splitting or an accepted budget;
  the current monolithic bundle warning is not a production-readiness pass.
- `LOW-MEM-007`: DataHub and inference provider bodies are streamed through fixed pre-JSON limits
  (8 MiB and 2 MiB respectively); an upstream `Content-Length` omission cannot bypass the limit.

## 5. Configuration profiles

The repository commits examples, never deployed values:

- `.env.mac-development` is created from the Mac example and uses the native Ollama plus explicitly
  selected external Redis/MinIO/DataHub endpoints.
- `.env.wsl-preparation` is created from the WSL example and uses runtime web origins, local or
  private-network Redis/Neo4j/APISIX, and external services.

The WSL host remains `APP_ENV=development` while using the development-only intranet
OpenAI-compatible and Neo4j adapters. Calling it production does not make those adapters production
safe. A future production profile requires accepted TLS/secret-provider/runtime-adapter changes and
must not bypass validation.

## 6. Migration and rollback

1. Freeze a clean source commit and release index.
2. Verify Mac arm64 functions against external Redis/MinIO and native Ollama.
3. Quiesce mutating API routes, relay and workers; record the cut line.
4. Create logical PostgreSQL and object manifests. Keep the source environment intact.
5. Verify and import the amd64 images/source on WSL.
6. Start PostgreSQL/Keycloak, restore into an isolated target, then run Alembic to the recorded head.
7. Configure external endpoints, initialize/reconcile buckets and rebuild non-canonical projections.
8. Run positive/negative smoke tests before routing users.
9. Roll back by stopping target writers and returning traffic to the untouched source. Reverse-copy
   only a reviewed target delta; never merge volumes.

## 7. Acceptance gates

- all repository static, backend and frontend gates pass;
- every Compose profile renders with the selected environment and without hidden pulls/builds;
- browser tests prove the 100-row/request bound and no selection scan;
- runtime web configuration is verified with two different OIDC origins from one image;
- Redis cache/delivery policy and S3 authenticated bucket/multipart/presign contracts pass;
- source and target backup/restore checksums plus Alembic head agree;
- target resource inventory, load/soak, RPO/RTO and independent failure review are recorded;
- no document labels a one-host deployment HA or production-ready.

## 8. Explicitly open decisions

The accountable operator must still supply WSL CPU/RAM/disk, endpoint DNS/TLS, credentials, the
approved Redis/MinIO distributions and exact digests, and whether the first WSL setup is a clean
pilot or a data-bearing migration. Missing target access is an external gate, not permission to
invent evidence.
