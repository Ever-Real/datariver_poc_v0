# dev_deploy refactor acceptance (DEV preparation only)

Baseline Product: `2bd5494d6f100abc8e50a844e0d01c30b93cc698`
Original source candidate: `938fa884ff1ada02db67f2e8c83f010c298c8440`
Final source candidate: `b0d0dd074762a170b8fb6514a92c463dcaecaf81`
Structure commit: `456b0ae1`; smoke commit: `d900f6be`; bounded review correction: `b0d0dd07`.
Actual PREP runtime: **NOT_RUN / pending environment and explicit approval**.
No newer actual PREP success evidence replaced the operator's Product2bd5494 / smoke6of6 baseline.

## Baseline contract (source evidence: exact Product and Handoff, not dev HEAD)
| Area | Preserved contract / evidence | Classification |
|---|---|---|
| Product/image | 2bd5494 Product, 4473135 evidence, 5ae0e49 handoff; operator SMOKE6/6. 938 candidate is source-build-only. New source commit/image recorded separately. | UNCHANGED baseline; new build identity |
| Services | Single Node serves API + built React; web, pgvector, neo4j, redis in Compose. DataHub/Kafka/schema registry/LLMs/Airflow/MinIO external. No FastAPI, worker or DAG source deployed. | UNCHANGED |
| Platform/dependencies | linux/amd64; Node22.19.0-bookworm-slim, pgvector0.8.2-pg17-bookworm, Neo4j2026.06.0, Redis8.2.6-bookworm; npm lock unchanged versions. Public/internal registry or approved cache required; no offline claim. | UNCHANGED |
| Ownership/state | datariver-prep39083/web/39083; network datariver-prep39083-services; pgvector-data, neo4j-data, neo4j-logs exact project volume names. Redis ephemeral LFU cache, no persistent volume. | UNCHANGED |
| Startup | config/provider preflight -> preserved/fresh state services -> inspect/reconcile admin/schema -> Web; K9 lease/restart recovery/scheduler precede listener; MCL scheduler starts after listener. Abort/wait/close ordering preserved. | UNCHANGED |
| Auth/schema | opaque sessions, fixed workspace000...0061, service subjects, exact table grants; original transaction/pool/schema invariants. All ten SQL migration filenames/content retained. | UNCHANGED |
| Env | core operator + optional sidecar + generated runtime credentials + fixed target values; Compose dotenv parsing, fixed project precedence; defaults and MCL discovery preserved. New default deploy/.env.prep, old path supported via --env-file. | EQUIVALENT_IMPLEMENTATION; live env UNVERIFIED |
| Credentials | existing .env.prep.runtime generated passwords/tokens reused; conflicts fail. Existing admin never reset; state services --no-recreate; no reset/prune/delete. | EQUIVALENT_IMPLEMENTATION |
| Proxy/CA | Build proxy separated from provider transport, required NO_PROXY merged, runtime CA mounted read-only. No provider env copied into image. | EQUIVALENT_IMPLEMENTATION |
| K9/index | canonical source inventory, source snapshot/active release/projector receipts and model/dimension-bound semantic index; daily scheduler/lease/checkpoint unchanged. | UNCHANGED |
| MCL | broker/schema discovery, topic/hash contract, provider/auth/TLS preserved; canonical39083 client/group. Existing39081 overrides only identities. Current capture required; history RETENTION_EXPIRED accepted degraded. | UNCHANGED; live env UNVERIFIED |
| Chat | original classifier/composer prompts, token budget/model/timeout/transport, route and scoped evidence policy preserved byte-for-byte inside function AST. | UNCHANGED |
| Quality/GX | PREP provider preflight reads DataHub ASSERTION + external Airflow quality dispatch DAG; `gx_quality_execution=READY` means dispatch readiness, not execution E2E. Current UI control-plane execution remains unavailable. Do not introduce FastAPI/worker to inflate scope. | UNCHANGED coverage; actual GX execution UNVERIFIED |
| Airflow/MinIO | controlled external DAG/token and existing MinIO bucket/prefix contracts. Smoke/provider preflight reads readiness, does not execute workflow/write source metadata. | UNCHANGED |
| Smoke6 | health, opaque admin login, DataHub inventory+direct glossary read, K9 graph+semantic read-back, MCL current/history contract, AUTO general provider. | HARD_GATE purposes preserved |
| Local39081 | Prior source-missing MCL and interrupted semantic attempt are not Product defects. No current local runtime/full smoke; real PREP env absent. | UNVERIFIED runtime |


## Function connections (paths on dev_deploy)

| UI feature | HTTP / use-case | Store/provider | Verification scope |
|---|---|---|---|
| Catalog/Search | /poc-api/datahub, modules/catalog/application | authorized DataHub inventory, PostgreSQL/vector/cache | canonical DataHub/glossary; selected table readback |
| Chat | /poc-api/llm/chat, modules/chat/application | classifier/composer, scoped catalog/vector/graph evidence | AUTO general/search/graph + directVECTOR/GRAPH, grounded evidence |
| Registration | /api/v1/registration and bulk routes, modules/registration | controlled Airflow + MinIO + metadata mutation | existing request/state/auth regressions; live workflow NOT_RUN |
| Governance | /poc-api/change-requests, modules/governance | versioned PostgreSQL state/CR transitions | existing transition/authorization regression |
| Quality/GX | frontend app/api.ts, modules/quality/domain | DataHub profile/assertions; external DAG availability | assertion read+dispatch readiness only; execution E2E NOT_RUN |
| Knowledge/Graph | knowledge routes, modules/knowledge | PostgreSQL release/receipts and Neo4j readback | published version+snapshot, scoped graph relationship evidence |
| K9 | managed-assets, modules/k9 | canonical source/projector/semantic receipt stores and daily scheduler | exact lifecycle snapshot/projector readiness, graph content |
| MCL | /api/v1/change-history, modules/mcl | Kafka/schema contract/checkpoint, PostgreSQL events and scheduler | current caught-up; history exact or retention-expired gap |
| Admin/Auth | /auth and admin routes, modules/admin + auth | opaque sessions, users/grants/workspace/credential store | legacy HTTP/auth negative regressions; no reset |
| Monitoring | capabilities + dashboard config, modules/monitoring | provider read probes and approved dashboard links | source parity; live provider NOT_RUN |

## Smoke changes and protected meaning

| Original check | Purpose / class | Cost and observed issue | Change / replacement verification |
|---|---|---|---|
| retryReady retries every failure for1200s | PROGRESS_WAIT; configuration/auth HARD_GATE | source missing,401,terminalFAILED waited needlessly | typed progress/transient reads only; no blind mutation retry; negative tests |
| request300s inside readiness budget | PROGRESS_WAIT | request could exceed remaining stage time; final timeout masked known pending code | AsyncLocalStorage deadline bounds each request; preserve last classified state at deadline |
| focused general + canonical general | REDUNDANT_WORK | same question/provider called twice per deployment | canonical6/6 once, same-run same-source/origin general proof reused in features |
| first25 dataset search | REGRESSION_ONLY target assumption | TABLE/lineage might be later or absent | bounded10pages/20lineage reads; explicit NO_TEST_DATA; no empty E2EPASS |
| directGRAPH labelled broadly | HARD_GATE feature coverage | direct route did not prove AUTO classification | separate AUTO search/graph, directVECTOR/GRAPH; evidence tied to table and live relation readback |
| GENERAL selected_mode only | HARD_GATE real response | empty answer could pass | nonempty actual answer required, negative regression |
| K9 active release/content/semantic | HARD_GATE | legitimate initial collection cost | unchanged readback/receipts/scope; no rebuild/reset/skip |
| history gap | DATA_QUALITY_WARNING only exact retention expiry | historical data outside retention cannot be restored by retry | existing RETENTION_EXPIRED rule retained; missing source/UNKNOWN still fail |

Initial collection/embedding cost is unchanged; existing canonical scheduler locks and snapshot/model/version validation decide reuse.
No live timing/provider-call savings claimed on DEV without PREP env. Same general operation removed once per deployment;
readiness polling makes read-only requests. Receipt adds application HTTP request count and elapsed milliseconds, not a new dashboard.

## Structural limits and safety

379 function bodies extracted with AST-based live dependency binding; original function bodies match except static entry path.
No framework, extra process, new deployment profile, worker/DAG deployment or language migration.
Remaining coupling: catalog/chat/knowledge application functions share explicit lazy bootstrap bindings, composite state-store,
frontend API compatibility adapter. Pure Quality projections are separated; not all modules are pure domains.

All ten migration filenames and SQL bytes preserved. Rendered Compose parity matched service env, resources, ports,
security, network and volume identity (source image/build definition and schema directory are intentional path changes).
Existing state services preserve containers/volumes; new clean installations pull missing approved base service images.
Source build consumes only `git archive HEAD`; `.env*`, runtime, local dependencies/output cannot enter context.
Artifact-only known-good image/tag is preserved for rollback. Database rollback is a separate operator decision.

## Validation

Candidate `b0d0dd074762a170b8fb6514a92c463dcaecaf81`, tracked clean with origin, 262 files.
Fresh origin clone source check PASS; no-cache linux/amd64 source build PASS.
Build input SHA256: `3c923bb8a7f1ca816aad73252cc79343caaf62a71628d1e4830dab847d645a06`.
New OCI index digest: `sha256:b10c1aa106f6b2489968419d46334fea0d13a8c9df46eeb362bb59190afd7dec`.
Revision label matches candidate; tag `datariver-dev-deploy-source:b0d0dd074762`.
Old Product image, artifact branch, ignored helpers, previous build output and other checkout sources were not build inputs.

- Original contract regressions: 121 PASS, zero failures/skips.
- Canonical smoke regression: 59 PASS; focused/retry: 9 PASS, zero failures/skips.
- 379 extracted function body equivalence checks PASS.
- Typecheck, strict lint, frontend production build PASS.
- Synthetic Compose env quoting/interpolation/proxy/credential reuse/drift checks PASS.
- Original/new rendered Compose service/network/volume/security contract comparison PASS.
- Local protected container ID/image ID/project/running/volume identities and known-good tag unchanged after build.
- Independent fixed-diff review PASS; Actual PREP env/runtime/live smoke NOT_RUN.

See [validation/result.json](validation/result.json), [build receipt](validation/fresh-clone-build.json),
and [regression commands](validation/README.md). DEV status: **READY_FOR_PREP_OPERATOR**.
Actual PREP deployment and runtime acceptance require its existing operational inputs and explicit approval.

GitGuardian original four incidents: exact Product SHA256 blob hashes in original provenance, FALSE_POSITIVE_HASH4.
New changed tracked source scanned: no credential patterns, tracked env or private key; secret values never printed.
Independent Sonnet integrated review once; concrete fixes followed by narrow fixed-diff verification PASS at final source.
No actualPREP deployment, migration, provider mutation or full live smoke executed on DEV.
