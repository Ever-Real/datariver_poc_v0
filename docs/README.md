# Controlled artifact index

| ID | Artifact | Purpose | Status |
|---|---|---|---|
| 00 | [Project plan](00_PROJECT_PLAN.md) | scope, work breakdown, milestones, gates | Baseline |
| 01 | [PRD](01_PRD.md) | users, outcomes, requirements, acceptance | Baseline |
| 02 | [Constraints](02_CONSTRAINTS.md) | legal, security, platform, operational limits | Baseline |
| 03 | [Architecture](03_ARCHITECTURE.md) | contexts, ownership, runtime and data flows | Baseline |
| 04 | [Feature specification](04_FEATURE_SPEC.md) | behavior by module | Current-source summary; target gates open |
| 05 | [API specification](05_API_SPEC.md) | implemented HTTP contracts and backlog | Current-source summary; target gates open |
| 06 | [Data model](06_DATA_MODEL.md) | implemented DDL, core ERD and backlog schemas | Current-source summary; target gates open |
| 07 | [Security and ABAC](07_SECURITY_ABAC.md) | threat model, policy and enforcement | Baseline |
| 08 | [Deployment](08_DEPLOYMENT.md) | implemented profiles and production gates | Implemented baseline |
| 09 | [Test strategy](09_TEST_STRATEGY.md) | automated, performance, security and recovery gates | Baseline |
| 10 | [Semiconductor seed](10_SEMICONDUCTOR_SEED.md) | optional deep value-chain data pack | Implemented baseline |
| 11 | [Legacy migration](11_LEGACY_MIGRATION.md) | compatibility, migration, retirement | Baseline |
| 12 | [Acceptance report](12_ACCEPTANCE_REPORT.md) | executed evidence and known limitations | Development/integration accepted; production gates open |
| 13 | [Operations runbook](13_OPERATIONS_RUNBOOK.md) | backup, restore, recovery and incident procedures | Baseline |
| 14 | [Production hardening](14_PRODUCTION_HARDENING.md) | scale assumptions, P0-P3 disposition and decision gates | Active |
| 15 | [Legacy UX parity](15_LEGACY_UX_PARITY_PLAN.md) | v0.3 visual/workflow traceability, safe substitutions and staged acceptance | Active |
| 16 | [Phase execution checklist](16_PHASE_EXECUTION_CHECKLIST.md) | historical Phase 1/2 work and parity continuation record | Active historical scope |
| 17 | [Semiconductor seed workflow](17_SEMICONDUCTOR_SEED_WORKFLOW.md) | restartable external schema, DataHub lineage and Airflow operation | Implemented baseline |
| 18 | [Semiconductor governance taxonomy](18_SEMICONDUCTOR_GOVERNANCE_TAXONOMY.md) | DataHub glossary/tag hierarchy and deterministic enrichment workflow | Implemented baseline |
| 19 | [Two-person CR browser acceptance](19_CR_E2E_ACCEPTANCE.md) | target-environment OIDC/WebAuthn intake, independent review and completion evidence | Active acceptance gate |
| 20 | [Enterprise UI completion PRD](20_ENTERPRISE_UI_COMPLETION_PRD.md) | CR, Knowledge Studio, profile and administrator screen requirements with governed substitutions | Implemented; API gates open |
| 21 | [Enterprise UI completion checklist](21_ENTERPRISE_UI_COMPLETION_CHECKLIST.md) | requirement-to-component/API/test traceability for the current UI completion work | Implemented; external gates open |
| 22 | [Four-menu use cases and architecture review](usecases.md) | Search, Registration, CR and Knowledge use cases, integration gates and proposed ERDs | Step 1 design baseline |
| 23 | [Catalog DataHub ingestion, metadata and export operation](23_CATALOG_DATAHUB_INGESTION_AND_EXPORT.md) | PostgreSQL/Oracle profile and Created Date limits, description sync, safe export activation | Implemented contract; remote activation gates open |
| 24 | [Low-resource multi-architecture deployment PRD](24_LOW_RESOURCE_MULTIARCH_DEPLOYMENT_PRD.md) | arm64/amd64 parity, dependency placement, configuration and migration acceptance | Active |
| 25 | [Low-resource multi-architecture execution checklist](25_LOW_RESOURCE_MULTIARCH_EXECUTION_CHECKLIST.md) | phased implementation and target-environment evidence | Active |
| 26 | [Mac arm64 to WSL amd64 migration runbook](26_MAC_TO_WSL_MIGRATION_RUNBOOK.md) | exact-source/image transfer, object reconciliation, logical restore and rollback | Active target gate |
| 27 | [Policy Book and Admin governance PRD](27_POLICY_BOOK_ADMIN_GOVERNANCE_PRD.md) | access levels, assignment evidence, retention and approval-gated Admin completion | Active; Phase 3 local source complete |
| 28 | [Policy Book execution checklist](28_POLICY_BOOK_EXECUTION_CHECKLIST.md) | phase gates and exhaustive Admin function inventory | Phase 3 local source complete; target acceptance gates open |
| 29 | [Master execution backlog](29_MASTER_EXECUTION_BACKLOG.md) | current delivery checklist, risk status and final artifact order | Active; owner-directed Phase 8 summaries, remaining hardening deferred |
| 30 | [Typed BULK catalog metadata rows PRD](30_TYPED_BULK_CATALOG_METADATA_PRD.md) | grouped table/column/domain/tag/term row contracts and TDD gates | Local source complete; external acceptance gates open |
| 31 | [Phase 4 Knowledge entry gate](31_PHASE4_KNOWLEDGE_ENTRY_GATE_PRD_CHECKLIST.md) | atomic governed publication, classification envelope and independent provider preflight | Local implementation complete; external provider gates open |
| 32 | [Phase 5 durable Knowledge source jobs](32_DURABLE_KNOWLEDGE_SOURCE_JOBS_PRD_CHECKLIST.md) | pinned, fenced and recoverable PDF-to-DRAFT execution | Local source/DB/audit complete; target gates open |
| 33 | [Phase 6A WSL bootstrap and connector network](33_WSL_BOOTSTRAP_AND_CONNECTOR_NETWORK_PRD_CHECKLIST.md) | fail-fast secret intake and deterministic shared-network startup | Local source/audit complete; target WSL gate open |
| 34 | [Phase 6B atomic Sharing invocation](34_ATOMIC_SHARING_INVOCATION_PRD_CHECKLIST.md) | subject-bound grants, exact replay, atomic quota/result evidence and retention binding | Local source/DB complete; target load/identity/retention gates open |
| 35 | [Phase 6C atomic Sharing hardening](35_ATOMIC_SHARING_HARDENING_PRD_CHECKLIST.md) | failure rollback, Subject/context negatives, replay expiry and lock interleavings | Local source/DB complete; target load/identity/retention gates open |
| 36 | [Phase 6D Admin/auth session epoch](36_ADMIN_AUTH_SESSION_EPOCH_PRD_CHECKLIST.md) | latest-only identity hydration, request boundary fencing and Admin context teardown | Local source/audit complete; target IdP/browser gates open |
| 37 | [Phase 6E web Nginx security headers](37_WEB_NGINX_SECURITY_HEADERS_PRD_CHECKLIST.md) | recursive header inheritance, API normalization and native-image behavior gate | Local source/runtime/audit complete; target gates open |
| 44 | [Knowledge Studio redesign PRD](44_KNOWLEDGE_STUDIO_REDESIGN_PRD.md) | Registry drawer, full-screen Studio, T-Box proposal and A-Box whitelist design | Approved; Phase 1 implementation |
| 45 | [Knowledge Studio redesign execution checklist](45_KNOWLEDGE_STUDIO_REDESIGN_EXECUTION_CHECKLIST.md) | phased contracts, migration, UI and evidence gates for the redesign | Active; Phase 0 approved |
| 46 | [Knowledge Studio Phase 5 release report](46_KNOWLEDGE_STUDIO_PHASE5_RELEASE_REPORT.md) | governed schema/mapping publication, adapter boundary, cleanup and remaining operational gates | Local-source release candidate |
| 47 | [Knowledge Studio Phase 6 cutover preparation](47_KNOWLEDGE_STUDIO_PHASE6_CUTOVER_PREP.md) | RC tag, revision `0061`, Docker restart and Graph Builder scaffold acceptance commands | RC cutover preparation |
| 48 | [Air-gapped source-free amd64 Pilot PRD/checklist](48_AIR_GAPPED_SOURCE_FREE_PILOT_PRD_CHECKLIST.md) | exact-commit image bundle, source-free target, one-shot migration and external gates | Local implementation complete; target gates open |
| 50 | [Pilot deployment and integration guide](50_PILOT_DEPLOYMENT_AND_INTEGRATION_GUIDE.md) | copy/paste artifact transfer, environment/secret setup, deployment, integration and Day 2 operations | Operator runbook; target gates open |
| 51 | [Knowledge Phase 6 cutover QA remediation](51_KNOWLEDGE_PHASE6_QA_REMEDIATION.md) | domain safety net, persistent Knowledge shell, resizable/version-focused Registry drawer and governed edit/archive actions | Local source verified; target browser/PostgreSQL gates open |
| 52 | [GX quality management PRD/checklist](52_GX_QUALITY_MANAGEMENT_PRD_CHECKLIST.md) | governed DataHub Profile, typed Rule, isolated GX execution and authorization-pruned dashboard contract | Phases 1–5 and local Phase 6 gates complete; mutations and target Profile/source/WSL gates remain closed |
| 53 | [Phase 7 integrity audit](53_PHASE7_INTEGRITY_AUDIT.md) | one-pass source/migration/secret audit, V4 retention administration and fail-closed dispatch capacity | Local static/focused gates complete; Phase 8 runtime and target gates open |
| 54 | [Phase 8 Quality authoring and execution readiness](54_PHASE8_QUALITY_AUTHORING_AND_EXECUTION_READINESS.md) | V2 field directory, atomic Rule commands, manual Run outbox and runtime readiness | Local source/PostgreSQL 17 gates complete; target source/Profile gates remain open |
| 55 | [Phase 9 Governance Document library](55_PHASE9_GOVERNANCE_DOCUMENT_LIBRARY.md) | immutable document/Template versions, approval, safe HTML, MinIO and knowledge projection | Local source/PostgreSQL 17/MinIO/runtime gates complete; target gates open |
| 56 | [Governed Monitoring dashboard tabs](adr/0090-governed-monitoring-dashboard-tabs.md) | Workspace Monitoring tab presentation, administrator update and exact-origin embed boundary | Accepted; local implementation |
| 57 | [External Monitoring dashboard links](adr/0095-external-monitoring-dashboard-links.md) | arbitrary credential-free HTTP(S) Dashboard Links with a disabled-first iframe boundary | Accepted; local implementation |
| 58 | [Administrator-approved Monitoring frames](adr/0097-administrator-approved-monitoring-frames.md) | persisted Admin approval, sandboxed HTTP(S) frames and target-policy fallback | Accepted; local implementation |

Independent review records: [Data Architect](reviews/2026-07-14_DATA_ARCHITECT_REVIEW.md),
[Data Engineer/SRE](reviews/2026-07-14_DATA_ENGINEER_REVIEW.md), and
[GX Quality Phase 0](reviews/2026-07-30_GX_QUALITY_PHASE0_REVIEW.md).

Architecture decisions are immutable records under `adr/`. Superseded artifacts remain in Git and link to their replacement; they are not silently overwritten.

Current retention decisions: [governed retention and immutable archive](adr/0010-governed-retention-and-immutable-archive.md), [maintained S3 and archive promotion](adr/0012-maintained-s3-and-immutable-archive-promotion.md), [Chat active-policy binding](adr/0018-chat-retention-policy-binding.md), and [archive-only execution control plane](adr/0037-retention-execution-control-plane.md).

Current administrator decisions: [hardware WebAuthn and governed password fallback](adr/0009-hardware-webauthn-and-governed-password-fallback.md), [workspace access roles and development connection probes](adr/0024-workspace-access-roles-and-development-connection-probes.md), and [operator security modes and stable authentication renewal](adr/0025-operator-security-modes-and-stable-auth-renewal.md).
The development-only Governance Document password assurance composition is defined by
[ADR-0087](adr/0087-development-governance-document-password-assurance.md); it does not relax
production or unrelated high-risk Actions.

Current account/workflow/runtime decisions: [expiring membership renewal](adr/0026-expiring-human-membership-renewal.md), [CR System-role authority](adr/0027-change-request-system-role-authority.md), and [development System Settings startup activation](adr/0028-development-system-configuration-startup-activation.md).

Current development knowledge-integration decision: [intranet OpenAI-compatible adapter](adr/0030-development-intranet-openai-compatible-adapter.md).
Private gateway path prefixes, path-like model IDs and governed runtime reranking are refined by
[ADR-0065](adr/0065-intranet-inference-gateway-prefix-and-runtime-reranking.md).
The exceptional exact-host opt-in for a company-approved gateway resolving to public addresses is
defined by [ADR-0066](adr/0066-approved-public-enterprise-inference-hosts.md).

Current local identity-lifecycle decision: [governed Keycloak identity provisioning](adr/0031-governed-keycloak-identity-provisioning.md).

Current Linux/WSL source-host scheduling decision: [Airflow loopback bridge](adr/0032-linux-source-host-airflow-loopback-bridge.md).

Current external infrastructure connector decision: [external Redis and S3 connector control plane](adr/0033-external-redis-and-s3-connector-control-plane.md).

Current multi-architecture release decision: [runtime configuration and release bundles](adr/0034-multi-architecture-runtime-configuration-and-release-bundles.md).

Current low-resource client and preparation Chat decision: [bounded client state and preparation Chat provider](adr/0035-bounded-client-state-and-preparation-chat-provider.md).

Current Policy Book decision: [normalized RBAC rules and Admin approval gates](adr/0036-policy-book-rbac-and-admin-approval-gates.md).

Current bounded Admin decision: [bounded navigation and delta assignment](adr/0038-bounded-admin-navigation-and-delta-assignment.md).

Current Registration execution decision: [accountable execution and bounded provider evidence](adr/0041-accountable-registration-execution-and-evidence.md).

Current typed BULK decision: [catalog metadata row and group contract](adr/0042-typed-bulk-catalog-metadata-profiles.md).

Current governed Knowledge entry decision: [atomic publication and independent capability gates](adr/0043-governed-knowledge-publication-and-provider-capability-gates.md).

Current durable Knowledge source decision: [pinned and fenced PDF analysis jobs](adr/0044-durable-knowledge-source-analysis.md).

Current Sharing invocation decision: [atomic API-product invocation results](adr/0045-atomic-api-product-invocation-results.md).

Current administrator runtime decision: [bounded drill-downs and deployment-owned probes](adr/0046-bounded-admin-drilldowns-and-deployment-probes.md).
The exact-IP transport exception for fixed probes in DNS-less isolated networks is defined by
[ADR-0067](adr/0067-explicit-ip-plaintext-system-probes.md).
Development-only reconciliation of provider-derived ACTIVE Catalog System/Domain scopes into the
fixed local administrator membership is defined by
[ADR-0086](adr/0086-development-admin-active-catalog-scope-reconciliation.md); it does not widen
quarantine use, RESTRICTED Chat or production identity authority.

Current administrator completion evidence: [runtime completion checklist](38_ADMIN_RUNTIME_COMPLETION_CHECKLIST.md).

Current WSL source-validation decisions: [intranet HTTPS ingress](adr/0051-wsl-intranet-source-host-ingress.md),
[deployment-aware infrastructure](adr/0052-deployment-aware-source-host-infrastructure.md), and
[verified Neo4j source-host profile](adr/0053-verified-neo4j-source-host-profile.md), refined by
[pre-state local-image source validation](adr/0054-pre-state-local-image-source-validation.md) and
[preloaded Neo4j source validation](adr/0055-preloaded-neo4j-source-validation.md).

Current Knowledge Studio foundation decision: [persistent Studio drafts, weighted overlay merge,
endpoint aliases and managed default graphs](adr/0058-knowledge-studio-foundation-and-managed-graphs.md).
Its auto-save concurrency and browser recovery boundary is defined by
[Knowledge Studio offline recovery and ETag conflicts](adr/0059-knowledge-studio-offline-recovery-and-etag-conflicts.md).
The in-memory layer/step continuity, managed-domain CRUD, alias-array contract and bounded real
document Proposal path are defined by
[ADR-0072](adr/0072-knowledge-studio-session-domains-and-bounded-document-proposals.md) and
[ADR-0073](adr/0073-knowledge-domain-author-bootstrap.md). The single domain resource, bounded
multipart ingress, exact catalog Proposal pin and React Flow projection refinements are defined by
[ADR-0074](adr/0074-knowledge-studio-unified-domain-and-proposal-integrity.md).
The isolated `admin.manage` assurance and development password-reauth boundary for domain rename
and archive is defined by
[ADR-0075](adr/0075-knowledge-domain-administrator-assurance.md).
The active-layer bidirectional connection rule, canonical hierarchy projection, bounded provider
grammar, auditable latest-block deletion and separate information/profile workspaces are defined by
[ADR-0076](adr/0076-knowledge-studio-interaction-provider-and-profile-boundaries.md).
The governed Quality bounded context, DataHub Profile projection, PostgreSQL-first GX execution,
isolated worker, typed Rule and sanitized dashboard/result boundary are defined by
[ADR-0077](adr/0077-governed-gx-quality-control-plane.md).
The additive Profile collector boundary, local Catalog source-version watermark, frozen
`POLICY_BOOK_V3`, exact `POLICY_BOOK_V4` extension and typed Profile Snapshot hold are defined by
[ADR-0078](adr/0078-quality-profile-retention-v4-and-collector-boundary.md).
The fail-closed V2 authoring directory, bounded atomic Rule proposal and server-derived
review/activation/manual Run commands are defined by
[ADR-0079](adr/0079-quality-authoring-readiness-and-manual-run-commands.md).
The search-integrated Quality Evidence, asset-centric workspace and reusable common Rule Template
to atomic multi-asset Rule Set mapping are defined by
[ADR-0081](adr/0081-user-centric-quality-workspace-and-common-rule-templates.md).
The permission-scoped schema Quality dashboard, managed accuracy/completeness/timeliness
definitions, Catalog hierarchy reuse and fact-only report boundary are defined by
[ADR-0088](adr/0088-schema-quality-dashboard-and-managed-indicators.md).
The immutable Governance Document aggregate, safe HTML/import boundary, create-only MinIO
artifacts, independent approval and authorized vector/Neo4j projection are defined by
[ADR-0080](adr/0080-governance-document-library-and-knowledge-projection.md).
Its Bleach policy, exact-version Presigned download, pgvector exact search, declared
`GovernancePolicy -> Dataset/Term` projection and Chat citation boundary are refined by
[ADR-0082](adr/0082-governance-document-pgvector-download-and-chat-grounding.md).
The managed Governance viewer, controlled three-document starter catalog, versioned hierarchy,
readable private object basenames and authorized JSON export are defined by
[ADR-0091](adr/0091-managed-governance-document-viewer-and-export.md).
Semantic `AUTO` Chat routing is defined by
[ADR-0085](adr/0085-semantic-chat-route-classification.md), and its server-observed live workflow
progress boundary is defined by
[ADR-0089](adr/0089-live-chat-workflow-progress-events.md).
Workspace-scoped Monitoring dashboard tabs, administrator updates and the exact-origin frame
boundary are defined by [ADR-0090](adr/0090-governed-monitoring-dashboard-tabs.md). Registration of
credential-free HTTP(S) links from any origin, while preserving the existing disabled-first iframe
gate, is defined by [ADR-0095](adr/0095-external-monitoring-dashboard-links.md).
Fresh administrator persistence as iframe approval, the bounded HTTP(S) frame CSP and the target
site frame-policy fallback are defined by
[ADR-0097](adr/0097-administrator-approved-monitoring-frames.md).
The consolidated Knowledge Information workspace, immutable-Release Property Profiles, governed
Catalog tables and bounded document-Proposal proxy bridge are defined by
[ADR-0083](adr/0083-knowledge-information-property-profiles-and-bounded-proposal-timeout.md).
The unified Registry/Studio/instance operating model, typed alias delivery policy and
authorization-scoped Chat graph selection are defined by
[ADR-0092](adr/0092-knowledge-asset-lifecycle-delivery-and-chat-scope.md) and the
[Knowledge Asset operating model](56_KNOWLEDGE_ASSET_OPERATING_MODEL.md).
The governed PDF worker's compatible expansion to CSV, TXT, JSON, XML, HTML and macro-free
DOCX/XLSX/PPTX evidence sources is defined by
[ADR-0093](adr/0093-governed-multiformat-knowledge-source-analysis.md).
Published Studio Release-pinned database ingestion, its dedicated worker/database principal,
typed DRAFT Changeset result and vector-preparation evidence are defined by
[ADR-0094](adr/0094-governed-studio-database-ingestion.md).
The Step 3 child aggregate and provider boundary are defined by
[Knowledge Studio A-Box binding drafts](adr/0060-knowledge-studio-abox-binding-drafts.md).
Its row-sample dry run and version-fenced ingestion readiness evidence are defined by
[Knowledge Studio dry-run preview and pre-flight](adr/0061-knowledge-studio-dry-run-preview-and-preflight.md).
Its maker-checker schema/mapping publication, separate active Studio Release and physical adapter
boundary are defined by
[Knowledge Studio governed schema and mapping publication](adr/0062-knowledge-studio-governed-schema-publication.md).

The source-free isolated amd64 Pilot packaging and deployment boundary is defined by
[ADR-0063](adr/0063-source-free-air-gapped-pilot-release.md).
Admin deployment-environment identity and the non-privileged operator-command handoff are defined
by [ADR-0064](adr/0064-admin-environment-identity-and-operator-handoff.md).
Its Admin button interaction, live connection badges and source-host governed Chat bootstrap are
refined by
[ADR-0068](adr/0068-live-connection-status-and-source-host-chat-governance-bootstrap.md).

The route-backed Knowledge Studio modal, bidirectional typed T-Box editor, proposal conflict
handling, durable A-Box ingestion and release-scoped Neo4j vector shadow are defined by
[ADR-0069](adr/0069-route-backed-ontology-builder-and-vector-shadow.md).
The normalized Class/Property/Relationship Draft schema, canonical `subClassOf` hierarchy and
forward-only layer dependency locks are defined by
[ADR-0070](adr/0070-normalized-tbox-hierarchy-and-layer-dependencies.md).
Unicode schema identifiers, named Class hierarchy edges and the unified Proposal entry are defined
by [ADR-0071](adr/0071-unicode-tbox-and-integrated-proposal-entry.md).

## Change control

- Requirements use stable IDs (`FR-*`, `NFR-*`, `SEC-*`).
- APIs use `/api/v1` until an incompatible contract requires a new major path.
- Database change requires an Alembic migration and an update to the data model.
- Architecture changes require an ADR.
- A release requires links from the acceptance report to machine-generated evidence.
