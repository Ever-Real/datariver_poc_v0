# Low-resource multi-architecture execution checklist

This checklist is evidence-driven. `[x]` means the named repository evidence was actually executed;
`[ ]` remains open until the target system or accountable operator supplies it.

## Phase 0 — merged baseline and risk intake

- [x] `origin/main` fetched and compared with the prior catalog branch; both trees matched at merge
  commit `313e59a`.
- [x] work moved to `codex/multiarch-external-connectors` without dropping uncommitted connector
  changes.
- [x] Redis/S3 externalization committed as `73e7dae`.
- [x] baseline Ruff, strict mypy, 734 backend tests, 163 frontend tests, typecheck, lint, build,
  Compose matrix, static verifier, shell syntax and deterministic migration regeneration passed.
- [x] independent pagination, architecture and multi-architecture release audits performed.

## Phase 1 — architecture and configuration contract

- [x] ADR-0034 and deployment PRD define alias normalization, per-architecture artifacts, runtime
  web configuration, single environment source and truthful Single-node Pilot labeling.
- [x] selected env-file support is implemented in Compose/bootstrap/source-host tooling.
- [x] the canonical example and generated Mac/WSL profile workflow contain no literal credentials.
- [x] named external connector network and WSL host-gateway fallback render correctly.
- [x] System Settings startup activation is disabled in both selected deployment profiles.

## Phase 2 — low-resource product correction

- [x] remove catalog `200/500/1000/all`; enforce one request with `limit<=100` per page action.
- [x] separate facet refresh from cursor navigation.
- [x] open tree/lineage detail without scanning result pages.
- [x] evict collapsed tree branches, cap one retained branch at 200 nodes and add regression evidence.
- [x] record remaining field/search/XLSX/lineage performance gates without claiming completion.
- [x] split feature routes; the largest production JavaScript chunk is 241.17 kB and the former
  861.17 kB monolithic-chunk warning is gone.

## Phase 3 — release artifacts

- [x] exporter accepts Docker aliases and emits only normalized `arm64`/`amd64` names; shell,
  Compose and static contracts passed.
- [x] exporter refuses a dirty tree and records exact commit/toolchain provenance; the dirty-tree
  negative check exited `2` before Docker access.
- [x] web configuration is runtime-bound in a generated no-store script. One arm64 image ID
  `sha256:7f474774499c…` was started with both Mac `18081/38102` and WSL `8081/8080` origins and
  generated the correct configuration without rebuild.
- [ ] source bundle, platform bundle, optional bundle and release index checksums are generated.
- [ ] import verifier rejects checksum, platform, commit and image-inventory mismatches. The first
  real arm64 bundle exposed and fixed a relative source-bundle path defect; regenerate from the
  corrected commit before accepting this gate. Preflight also replaced cross-platform wrapper
  builds with exact-digest platform pulls so external image identity is preserved. The first amd64
  attempt stopped before build on a Bash 3.2 empty-array incompatibility; the optional-image loop
  now has an explicit cardinality guard and must be rerun from the corrected commit.
- [ ] core, PostgreSQL, Redis, MinIO and Neo4j OCI indexes are digest-pinned. Redis/MinIO
  redistribution and target vulnerability/license acceptance remain operator gates; the
  nonexistent MinIO `2025-10-15` image tag was replaced by the available `2025-09-07` image.

## Phase 4 — Mac `linux/arm64` development PC

- [x] Docker daemon reports `linux/arm64`, 6 CPUs and 20,942,880,768 bytes memory; Buildx advertises
  both `linux/arm64` and `linux/amd64`. Disk headroom remains an export-time gate.
- [ ] external Redis cache/delivery endpoints pass distinct policy/authentication probes.
- [ ] external MinIO/S3 buckets pass authenticated bucket, multipart, copy, checksum, CORS and
  presign probes; anonymous access is denied.
- [ ] PostgreSQL/Keycloak/DataRiver start with the Mac env file and native Ollama path.
- [ ] migration head, readiness, authentication, catalog, registration and selected knowledge
  smoke tests pass.
- [ ] arm64 release artifact checksums and rollback inputs are stored outside Git.

## Phase 5 — WSL `linux/amd64` preparation PC

- [ ] CPU/RAM/disk, Docker/Compose versions and `linux/x86_64→linux/amd64` mapping captured.
- [ ] exact source bundle and release artifacts pass import verification.
- [ ] PostgreSQL logical restore is rehearsed in isolation; Alembic reaches the recorded head.
- [ ] Keycloak import/issuer/redirect origins use WSL runtime values.
- [ ] Redis/Neo4j/APISIX local connector network or approved remote DNS/TLS paths pass.
- [ ] external MinIO/DataHub/Airflow/telemetry/LLM contracts pass without embedding credentials.
- [ ] positive/negative smoke, load/soak, backup/restore and rollback rehearsal evidence accepted.

## Phase 6 — promotion boundary

- [ ] no open P0/P1 release issue remains.
- [ ] independent reviewer confirms source, images, configuration and data reconciliation.
- [ ] branch is current with `origin/main`, commits are pushed and CI is green.
- [ ] preparation PC remains labeled Single-node Pilot.
- [ ] production/HA promotion is handled by a separate three-failure-domain decision and drill.
