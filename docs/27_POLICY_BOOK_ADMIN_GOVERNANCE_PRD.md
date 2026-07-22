# Policy Book, RBAC, retention and Admin governance PRD

## Objective and approval gates

DataRiver must demonstrate who may access each data class, how permitted data is treated, where it
may reside, why it may be processed, and how long it is retained. Canonical policy and execution
evidence belong in workspace-scoped PostgreSQL; DataHub, Redis, S3-compatible storage, Neo4j,
Airflow and inference providers remain fallible external systems.

Delivery is deliberately split into three approval-gated phases:

1. **RBAC database modelling**: normalized versioned Role data rules and exact assignment evidence.
2. **Data Retention backend scheduler**: bounded eligibility/claim/archive/read-back/hold recheck
   workflow under a dedicated least-privilege process. It remains disabled until Phase 2 approval.
3. **Admin UI integration**: wire every accepted Admin API, replace placeholders with explicit
   implemented or unavailable states, and expose policy evidence. It remains unchanged until Phase 3
   approval.

Completion of a phase does not authorize starting the next one. The accountable user must explicitly
approve the preceding checklist and residual risks.

## Policy model

Each workspace Role version may contain at most one rule for each classification: PUBLIC, INTERNAL,
CONFIDENTIAL and RESTRICTED. A rule contains:

- `NO_ACCESS`, `PARTIAL_ACCESS` or `FULL_ACCESS`;
- for partial access, exactly one typed treatment: `MASK`, `REDACT` or `TOKENIZE`;
- an allowlist of residency-region identifiers;
- an allowlist of processing purposes: metadata read, data read, export, analytics or model training;
- a canonical SHA-256 payload hash, exact Role version, creator and timestamp.

A missing rule is `NO_ACCESS`. A partial rule is denied when its trusted treatment adapter is not
available. These rules add a deny-capable policy-book layer; they never bypass current action,
workspace, clearance, System/Domain, classification-policy or RLS checks. Phase 1 does not claim to
mask external source rows: current catalog endpoints expose metadata, not arbitrary source data, and
future data-value adapters must invoke both the existing ABAC decision and this policy-book decision.

Role assignment keeps the materialized membership ABAC document for runtime compatibility, while a
normalized current assignment and append-only event record bind subject, Role ID/version,
membership version, canonical materialized-access hash and administrator actor. The access hash
excludes the optimistic expected membership version, so retrying the same Role and access semantics
cannot create false reassignment evidence. Existing reserved group markers are legacy
display hints, not evidence and not authority; an administrator must explicitly reassign those users
to create normalized evidence. Manual and fallback access documents cannot submit reserved markers;
only the Role-assignment path changes them together with normalized current/event evidence. That
path compares the marker against the locked Role key and rejects exact same
Role/version/materialized-access-hash reaffirmation. Before Phase 3, a Role-bound member's generic
access form therefore fails closed; the
approved Phase 3 UI must disable it and direct administrators to remove the Role first.

## Administration and separation of duties

- Read access requires an active, unexpired, human security-administrator membership.
- Role create/update/deactivate and assignment require recent hardware WebAuthn and prohibit
  self-access changes. Role-definition events bind the exact `admin.manage` decision ID and current
  assurance after rechecking the eligible human administrator membership under row lock.
- In-use Role security or data-rule definitions cannot change; users must first be reassigned.
- Role rules and assignment events are append-only to the application role. Current assignment rows
  permit only bounded state/version updates and no delete.
- Policy Book administration stores no provider credential, password, token or raw provider command.
- Retention policy and erasure approval never imply execution. Legal Hold always wins.

## Low-resource and portable deployment requirements

- List/read operations are bounded and set-based; Role rule reads use one batch rather than one query
  per rule.
- PostgreSQL and the application remain architecture-neutral. The same source revision and lockfiles
  build separate `linux/arm64` and `linux/amd64` images.
- Redis and S3/MinIO are external connector choices and never canonical RBAC/retention stores.
- A clean environment bootstraps secrets locally, applies Alembic through required revision `0041`,
  and never copies another machine's `.env`, secrets or volumes.

## Phase acceptance

Phase 1 requires domain negative tests, schema/request validation tests, forced-RLS and bounded-grant
tests, deterministic initial-migration generation, strict typing/lint/static checks, full backend
regression, documentation and a traceable commit. Phase 2 additionally requires scheduler crash,
lease, hold-race, archive read-back and zero-delete negative evidence. Phase 3 additionally requires
Admin route/component tests, browser authorization checks, pagination/memory checks and no-placeholder
acceptance for every function listed in the execution checklist.
