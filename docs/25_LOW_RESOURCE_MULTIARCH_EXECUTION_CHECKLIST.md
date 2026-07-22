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
- [ ] selected env-file support is implemented in Compose/bootstrap/source-host tooling.
- [ ] Mac and WSL example files contain no literal credentials and pass validation.
- [ ] named external connector network and WSL host-gateway fallback render correctly.
- [ ] System Settings startup activation is disabled in both selected deployment profiles.

## Phase 2 — low-resource product correction

- [x] remove catalog `200/500/1000/all`; enforce one request with `limit<=100` per page action.
- [x] separate facet refresh from cursor navigation.
- [x] open tree/lineage detail without scanning result pages.
- [x] evict collapsed tree branches, cap one retained branch at 200 nodes and add regression evidence.
- [x] record remaining field/search/XLSX/lineage performance gates without claiming completion.
- [x] split feature routes; the largest production JavaScript chunk is 241.17 kB and the former
  861.17 kB monolithic-chunk warning is gone.

## Phase 3 — release artifacts

- [ ] exporter accepts Docker aliases and emits only normalized `arm64`/`amd64` names.
- [ ] exporter refuses a dirty tree and records exact commit/toolchain provenance.
- [ ] web configuration is runtime-bound; one image passes two-origin verification.
- [ ] source bundle, platform bundle, optional bundle and release index checksums are generated.
- [ ] import verifier rejects checksum, platform, commit and image-inventory mismatches.
- [ ] base images and external Redis/MinIO distributions have approved exact tags/digests/licenses.

## Phase 4 — Mac `linux/arm64` development PC

- [ ] Docker daemon platform and available CPU/RAM/disk captured.
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
