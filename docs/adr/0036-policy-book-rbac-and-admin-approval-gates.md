# ADR-0036: Policy-book RBAC model and Admin approval gates

- Status: Accepted
- Date: 2026-07-23
- Refines: ADR-0009, ADR-0010, ADR-0024, ADR-0026, ADR-0031, ADR-0034

## Decision

DataRiver adds a normalized, workspace-scoped policy-book layer without replacing the existing ABAC
engine or PostgreSQL RLS. `iam.access_role_data_rules` stores immutable rules per exact Role version
and classification. A rule selects No, Partial or Full access and, for grants, explicit residency
regions and processing purposes. Partial access also selects one typed transformation. Missing rules,
unavailable transformations and scope mismatches deny. No rule can create access when action,
clearance, System/Domain, classification-policy or RLS checks deny it.

`iam.access_role_assignments` records the current subject-to-Role/version binding, exact membership
version and canonical materialized-access hash. The hash excludes the optimistic expected membership
version. `iam.access_role_assignment_events` is append-only assignment,
reassignment and removal evidence. Runtime membership attributes remain materialized for current ABAC
compatibility, but their `datariver-role-*` marker is not authority. Pre-existing marker-only users are
not assigned fabricated evidence; an administrator must explicitly reassign them.

Role rules and assignment evidence contain no credential. Rules and events have application
SELECT/INSERT only; current assignment has a bounded update-column grant and no delete. All three
tables use forced workspace RLS. Role mutations and assignments retain the recent hardware-WebAuthn,
self-change denial, optimistic locking and two-administrator boundaries.

Rule payloads are normalized once before persistence, response projection and hashing. Reserved
Role markers are rejected from manual/fallback membership documents and remain writable only by the
dedicated Role-assignment flow, which compares the marker with the locked Role row and rejects an
exact same Role/version/materialized-access hash no-op. Role-definition mutations persist the fresh
`admin.manage` decision ID in their outbox evidence and recheck the human administrator membership
under row lock. The 0041
bridge performs only explicit additive compatibility repairs, then fingerprints all required
column length/timezone/defaults, PK/UQ definitions, FK columns/targets/delete actions, CHECK SQL,
index columns/uniqueness and RLS mode/predicates, and fails closed on any remaining partial schema.

Work proceeds through three user approval gates: RBAC model, then retention scheduler, then Admin UI.
No later phase starts merely because the preceding code compiles. Retention execution remains
`DISABLED_NOT_READY`, and the UI continues to label unavailable Audit/Dictionary functions honestly,
until their separate gates pass.

## Consequences

- Policy authors can express the Policy Book's access level, treatment, locality and purpose without
  embedding provider credentials or arbitrary policy code.
- Exact Role-assignment evidence becomes queryable while existing authorization behavior remains
  compatible.
- Current catalog metadata APIs do not claim to mask source-system row values. A future data-value
  adapter must implement and attest the selected treatment before Partial access can allow a read.
- The same schema and source revision run on arm64 and amd64; Redis/S3/MinIO/DataHub placement does
  not alter policy ownership.
- Three additional IAM tables and evidence rows add bounded PostgreSQL storage cost. Role/rule reads
  must remain set-based and retention for the append-only evidence requires the governed Phase 2
  process, not ad-hoc deletion.
