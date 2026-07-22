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
- [x] evict collapsed tree branches, cap one retained branch at 200 nodes, retain at most eight
  expanded branches and add regression evidence.
- [x] cap retained DataHub schema enrichment at 1,000 unique fields, paginate serialization with a
  100-field default and 200-field maximum, and expose explicit total/total-exact/available/truncated
  metadata; record remaining search/XLSX/lineage performance gates without claiming them.
- [x] split feature routes; the largest production JavaScript chunk is 241.32 kB and the former
  861.17 kB monolithic-chunk warning is gone.

## Phase 3 — release artifacts

- [x] exporter accepts Docker aliases and emits only normalized `arm64`/`amd64` names; shell,
  Compose and static contracts passed.
- [x] exporter refuses a dirty tree and records exact commit/toolchain provenance; the dirty-tree
  negative check exited `2` before Docker access.
- [x] web configuration is runtime-bound in a generated no-store script. One arm64 image ID
  `sha256:7f474774499c…` was started with both Mac `18081/38102` and WSL `8081/8080` origins and
  generated the correct configuration without rebuild.
- [x] exact source bundle, arm64/amd64 core bundles, per-platform manifests and release-index
  checksums were generated from one clean final branch head and verified. Optional connector image
  archives remain an operator-controlled license/distribution choice, not a hidden core dependency.
- [x] import verifier rejects checksum, platform, commit and image-inventory mismatches. The first
  real arm64 bundle exposed and fixed a relative source-bundle path defect; regenerate from the
  corrected commit before accepting this gate. Preflight also replaced cross-platform wrapper
  builds with exact-digest platform pulls so external image identity is preserved. The first amd64
  attempt stopped before build on a Bash 3.2 empty-array incompatibility; the optional-image loop
  now has an explicit cardinality guard. The second amd64 attempt built the application images but
  exposed Docker Desktop's host-default view of a multi-platform external index; manifest checks
  and tar export now select the explicit target platform and must be rerun from the corrected
  commit. The cross-build host uses artifact-only verification; target daemon enforcement remains
  mandatory for WSL import. Tar inspection then found a digest-only PostgreSQL entry with no
  restorable tag; export now saves the already verified tag and rejects an archive missing any
  requested Compose image name. A later cross-build also proved that Docker Desktop may retain the
  host-platform tag after a platform-qualified OCI-index digest pull; export now refreshes the
  distributable tag and rejects it unless its platform child ID exactly matches the pinned index.
  Its first Mac run also exposed a BSD `awk` reserved-name conflict; the filter now uses a portable
  field variable. A corrupted-checksum negative test then exposed
  loop status masking; each checksum failure now returns immediately. The corrected verifier
  accepted both prior revision artifacts, and a deliberately corrupted checksum failed closed with
  exit 2; the same verifier is required for the clean final-head artifacts above.
- [x] core, PostgreSQL, Redis, MinIO and Neo4j OCI indexes are digest-pinned. Redis/MinIO
  redistribution and target vulnerability/license acceptance remain open operator gates; the
  nonexistent MinIO `2025-10-15` image tag was replaced by the available `2025-09-07` image.

## Phase 4 — Mac `linux/arm64` development PC

- [x] Docker daemon reports `linux/arm64`, 6 CPUs and 20,942,880,768 bytes memory; Buildx advertises
  both `linux/arm64` and `linux/amd64`. Disk headroom remains an export-time gate.
- [x] separate Redis cache/delivery endpoints authenticate. Cache reports `appendonly=no` and
  `allkeys-lfu`; delivery reports `appendonly=yes`, `appendfsync=everysec` and `noeviction`.
- [x] external MinIO/S3 buckets pass authenticated bucket, 5,242,897-byte multipart, presigned PUT,
  server-side copy, full-byte SHA-256, exact-origin CORS and anonymous-denial probes. The temporary
  probe objects were deleted after verification.
- [x] six accepted upload objects plus seven manual-metadata CSV objects were selected from the
  repeatable-read PostgreSQL evidence manifest, copied SeaweedFS→MinIO and re-read from both ends;
  the idempotent rerun reported `verified_existing=13` and `planned=0`.
- [x] PostgreSQL/Keycloak/DataRiver start with `.env.mac-development`; native Ollama advertises the
  configured `datariver-gemma4-dev:0.1` model.
- [x] Alembic `0040`, readiness, browser PKCE login, dashboard and catalog paging passed. At page
  size 100, moving page 1→2 retained exactly 101 table rows including the header and browser
  warning/error logs remained empty.
- [ ] a new canonical registration mutation and disabled knowledge paths were not enabled merely
  to produce smoke evidence. Their target-specific gates remain open until the feature is selected.
- [x] arm64 release checksums plus pre-cutover DataRiver/Keycloak logical dumps and their SHA-256
  files are stored under ignored local artifact directories. SeaweedFS remains online for rollback.
- [x] unused Mac Airflow/APISIX/Neo4j/telemetry containers were stopped without deleting volumes.
  Running DataRiver core plus Redis/MinIO used about 1.2 GiB at the observation point; retained
  SeaweedFS added about 215 MiB. Separately operated local DataHub used about 6 GiB and is the
  dominant Mac resource risk.

## Phase 5 — WSL `linux/amd64` preparation PC

- [ ] WSL `linux/x86_64→linux/amd64` mapping is captured; CPU/RAM/disk and Docker/Compose versions
  remain unavailable until the preparation PC is accessible.
- [ ] exact source bundle and release artifacts pass import verification.
- [ ] PostgreSQL logical restore is rehearsed in isolation; Alembic reaches the recorded head.
- [ ] Keycloak import/issuer/redirect origins use WSL runtime values.
- [ ] Redis/Neo4j/APISIX local connector network or approved remote DNS/TLS paths pass.
- [ ] external MinIO/DataHub/Airflow/telemetry/LLM contracts pass without embedding credentials.
- [ ] positive/negative smoke, load/soak, backup/restore and rollback rehearsal evidence accepted.

## Phase 6 — promotion boundary

- [x] no open P0/P1 source or Mac release issue remains; target-only WSL gates stay open below.
- [x] independent reviewers covered pagination, multi-architecture release safety and final
  data/SRE plus architecture consistency; accepted findings were resolved and rerun through the
  local final gates.
- [ ] branch is current with `origin/main` and local gates pass; push and remote CI remain open until
  the final branch publication succeeds.
- [ ] preparation PC remains labeled Single-node Pilot.
- [ ] production/HA promotion is handled by a separate three-failure-domain decision and drill.
