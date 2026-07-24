# Enterprise UI completion PRD

## Purpose

This document controls the React implementation of the requested Change Management, Knowledge
Management, profile and administrator experiences. It incorporates the recognizable interaction
intent of the read-only `../datariver_v0` reference while preserving the v1 domain, authorization,
canonical ownership and external-dependency boundaries.

Source precedence remains:

1. accepted v1 ADRs, security invariants and canonical ownership;
2. current v1 API and data contracts;
3. this PRD and its completion checklist;
4. the requested screen specification;
5. v0 layout and interaction intent only.

The v0 runtime, local-storage identity, direct provider writes, raw SQL/Cypher execution, mock API
fallbacks and browser-held credentials are never copied.

## Cross-cutting requirements

- `UI-BASE-001`: use the existing TanStack Table wrapper for operational tables.
- `UI-BASE-002`: use a reusable accessible four-stage Stepper for CR state presentation.
- `UI-BASE-003`: use `@xyflow/react` for lineage, release preview and ontology-draft graphs.
- `UI-BASE-004`: style new work with Tailwind CSS and the existing navy/cream design tokens without
  removing stable legacy CSS in the same change.
- `UI-BASE-005`: administrator navigation is derived only from `/admin/me` server operations. OIDC
  realm roles, URL values and browser storage are not authorization facts.
- `UI-BASE-006`: every async surface has loading, empty, unavailable and error states. A missing API
  never produces a fabricated record, count, test result or successful mutation.
- `UI-BASE-007`: tables and graphs remain keyboard-operable, labelled and usable at desktop and
  contained-scroll breakpoints.

## Change Management

- `UI-CR-001`: the new-CR dialog captures change-request title, server-verified requester,
  department, content, reason, priority/urgency, security classification and due date.
- `UI-CR-002`: target search uses authorized catalog search/detail APIs; manual targets append to
  the bottom. Table and column rows support inline logical description and requested-change text.
- `UI-CR-003`: template download is local, contains headers only and carries no provider identifier
  or credential. Spreadsheet import remains unavailable until a typed server parser contract is
  implemented; the browser does not parse untrusted Excel into an authoritative request.
- `UI-CR-004`: request evidence uses the existing private attachment API and 10 MiB per-file bound.
- `UI-CR-005`: detail uses a four-stage Stepper mapped from the canonical state machine. Navigation
  may inspect completed/current stages but cannot manufacture a state transition.
- `UI-CR-006`: stage 1 presents basic metadata, request evidence, reason and typed targets. Persisted
  request items remain immutable unless a version-fenced edit contract exists.
- `UI-CR-007`: stage 2 loads authorized catalog lineage for bound target assets and renders it with
  React Flow. Reviewer comments become the reason of an existing governed approval/transition.
- `UI-CR-008`: stage 3 displays real TEST attachments, approvals and transitions. Raw SQL is not
  generated or executed; a SQL-validation panel explicitly reports the missing typed test-result
  contract when no server evidence exists.
- `UI-CR-009`: stage 4 groups actual approval evidence into Developer, Data Steward and Admin lanes.
  Missing decisions show pending, never a fabricated approver or timestamp.

## Knowledge Management

- `UI-KG-001`: the left navigation contains Registry, Data Ingestion and a Knowledge GraphRAG Chat
  route that is distinct from the general Chat page and URL.
- `UI-KG-002`: Registry lists real knowledge graphs/assets with status, classification, version and
  active release. Selection opens an inspector with counts, timestamps, release history and React
  Flow preview. Graph creation uses the existing typed create API.
- `UI-KG-003`: Data Ingestion exposes Mode A (T-Box ontology) and Mode B (A-Box enrichment), target
  asset selection and the requested source/direct-definition tabs.
- `UI-KG-004`: Mode B PDF source analysis uses the durable `202` source-analysis job contract,
  resumes only owner-visible jobs and polls within a bounded, hidden-tab-aware window. Database
  sources and Mode A source-driven ontology generation remain disabled with their exact missing
  capability; the UI never routes them through an unrelated upload or fabricates an LLM proposal.
- `UI-KG-005`: direct ontology definition is a local draft editor. A safe CREATE-only schema subset
  may be parsed into draft nodes/edges and edited in React Flow; raw Cypher is never sent to or run
  by the server. Persisting uses typed changeset operations with provenance.
- `UI-KG-006`: Mode B PDF execution is available only for PUBLIC/INTERNAL graphs when the separately
  credentialed Knowledge worker and a complete Chat+Embedding pair are enabled. It exposes durable
  queue/run/retry/cancel/stale/failure states and navigates only a successful typed DRAFT result.
  Database/dynamic one-pass execution remains unavailable.
- `UI-KG-007`: Knowledge GraphRAG Chat is a separate page and conversation state. It can select only
  server-returned active graph releases and uses bounded analysis/evidence APIs; it never calls the
  general Chat route or submits raw Cypher.
- `UI-KG-008`: general Chat routing/prompt management remains a governed provider-profile backlog;
  no prompt or asset scope is stored as browser authority.

## Profile and administration

- `UI-ADM-001`: My Profile shows only verified OIDC/profile, current Workspace and server capability
  data. Identity/password changes are marked IdP-managed unless a typed identity-provider adapter
  is available.
- `UI-ADM-002`: Users and Systems are tabs in the administrator surface. Users uses the real
  membership list; selecting a user opens assigned/access facts and real CR/table counts. Creating
  an IdP user is not simulated.
- `UI-ADM-003`: Systems uses the canonical system directory and version-fenced assignee replacement.
  Schema scope, system create and delete controls name their missing typed contracts rather than
  mutating browser state.
- `UI-ADM-004`: Metadata Change Log and Security Log share one Audit/Log entry and switch through
  internal tabs. Audit/Log and Dictionary render only when the server grants administrator context.
  Their tables do not synthesize records. Export or mutation is enabled only when a separately
  authorized typed API exists.
- `UI-ADM-005`: Dictionary read search may use the authorized catalog vocabulary endpoint. Global
  mapping CRUD must be a governed proposal API; direct DataHub glossary mutation is prohibited.
- `UI-ADM-006`: Accounts & Access is the single entry point for Users, Systems, simple Role
  assignment, classification access, RESTRICTED Search exception grants and password-recovery
  approvals. The full ABAC access document remains available as an explicitly labelled advanced
  control rather than a separate primary menu.
- `UI-ADM-007`: Inference-provider eligibility approval is not a connection editor. It remains a
  nested security-policy view because classification routing binds approved immutable profile
  versions; endpoints and credentials cannot be created or changed there.
- `UI-ADM-008`: Retention policy, Legal Hold and erasure review remain executable governance
  controls, not duplicate documents. They are grouped under one Retention & Erasure entry while
  preserving Maker-Checker decisions, Legal Hold precedence and non-executing erasure review.
- `UI-ADM-009`: Development-only System Settings follows the v0 service-selector/YAML interaction
  but uses a fixed server inventory and server-owned templates containing only non-secret settings
  and mounted-secret reference names. Literal secret values are rejected, exact revisions retain
  TEST/activation evidence, and production continues to use deployment/provider controls.
- `UI-ADM-010`: The profile dropdown exposes only server-derived grouped administration entries;
  former leaf entries such as Role, provider, Legal Hold and erasure are reachable only inside
  their parent workspace and never become independent menu items.
- `UI-ADM-011`: reusable Role definitions are workspace-owned server data, not client constants.
  Assigning a Role materializes the existing governed membership access document; an in-use Role's
  security fields stay locked to avoid an unaudited bulk authorization change.
- `UI-ADM-012`: System Settings groups Chat Model, Embedding and Reranker in one LLM menu, provides
  SAVE, a fixed server-side TEST and explicit ACTIVATE of an implemented runtime consumer, and
  renders YAML as a compact terminal editor. ACTIVATE selects only the current TEST-passed revision;
  applying it requires API/relevant-worker restart and never implies hot reload.
- `UI-ADM-013`: the four classification rows are the server security contract. The UI presents
  them as a table and uses policy modes rather than deleting an enum row. RESTRICTED grants select
  a real authorized resource/System and exact subject and validity interval; missing Domain lookup
  remains unavailable rather than accepting an invented identifier.
- `UI-ADM-014`: the security-key label is device-neutral WebAuthn. The current accepted security
  ADR still requires recent hardware assurance for high-risk direct mutations; removing that gate
  requires a replacement ADR and cannot be achieved by hiding the enrollment control.
- `UI-ADM-015`: system responsibility has exactly two values, Developer and Data Steward. The
  directory does not synthesize a third assignee role. CR REVIEW and TEST require Developer evidence
  for every routed System; FINAL requires role-separated Developer and Data Steward evidence for
  every routed System plus one global Admin decision.
- `UI-ADM-016`: the four classification rows remain the security vocabulary while the current
  operating profile primarily uses CONFIDENTIAL (대외비) and RESTRICTED (극비). PUBLIC and INTERNAL
  remain explicit policy rows and are not deleted, renamed or silently mapped to another level.
- `UI-ADM-017`: an operator may hide manual Workspace switching without removing Workspace ABAC/RLS,
  and may disable DataRiver WebAuthn recognition without creating a password downgrade. These are
  deployment controls returned by `/auth/me`, not browser-writable Admin settings.
- `UI-ADM-018`: human Workspace memberships expire after six calendar months. The server exposes
  the final-30-day request eligibility fact, preserves one pending self-request and lets every
  eligible global Admin independently approve/reject while prohibiting self approval.

## Authentication rendering stability

- `UI-AUTH-001`: silent OIDC token renewal updates request-time credentials without recreating the
  application API client or retriggering every feature's load effect. A real Workspace change still
  resets workspace-scoped component state.
- `UI-AUTH-002`: profile hydration, API responses and retries are bound to the newest verified
  subject/session security epoch. Ordinary same-session renewal preserves unrelated feature state
  but revalidates Admin context; subject/session/security changes purge same-Workspace feature and
  global-search state before new data can render.

## Acceptance

- all requested surfaces are reachable with stable URL state and no overlap between Knowledge Chat
  and general Chat;
- non-admin users cannot discover administrator routes through the profile menu;
- CR creation, attachments, legal state transitions, knowledge graph creation/changesets/releases,
  membership reads and system assignment commands retain their existing real API behavior;
- graph canvases never collapse to zero size and show either authorized data, a labelled local
  draft, or an honest empty/unavailable state;
- no client mock API, hard-coded entity/count/approval/test success, provider credential, raw
  SQL/Cypher pass-through or cross-context write is introduced;
- frontend typecheck, lint, unit tests and production build pass; relevant backend/static gates stay
  green when an API contract changes.
