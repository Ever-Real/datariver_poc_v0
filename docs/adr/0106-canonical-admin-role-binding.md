# ADR-0106: Canonical Admin definition and protected local binding

- Status: Accepted
- Date: 2026-08-01
- Refines: ADR-0024, ADR-0103

## Context

ADR-0103 defines the exhaustive 64-human/5-service Action partition and advertises the protected
`admin.self_approve` capability as pending metadata. The existing generic Role-assignment path
materializes a Role into a membership. Reusing it for Canonical Admin would let a normal Role ID,
provisioning request or assignment mutation manufacture protected evidence and would blur the
difference between human service capability, fresh assurance and workflow self-approval.

The database also needs one server-owned capability definition per Workspace without promoting an
existing user. A local development administrator may receive a binding for testability, but that
must not become a production assignment API, a seed-based escalation or a browser-controlled
operation.

## Decision

Revision `0089` adds `role_kind`, `management_source` and an optional catalog version to
`iam.access_roles`. Existing and administrator-created Roles are `HUMAN_ROLE/HUMAN_ADMIN`. A
partial unique index permits at most one active server-owned `CANONICAL_ADMIN` definition per
Workspace, using the reserved `canonical-admin` key and the hash-pinned V2 catalog snapshot. New
Workspaces receive the same unassigned definition from a server-owned trigger. The migration adds
only those definitions: it creates no Subject, membership, generic assignment, assignment event or
Canonical Admin binding and therefore performs no user escalation. Generic Role quota counts only
`HUMAN_ROLE` rows.

`iam.canonical_admin_bindings` is a separate evidence table keyed by Workspace and Subject. It
binds the exact canonical Role/catalog version, capability hash, membership version and complete
membership-access hash. The application recomputes the evidence from the current active human
Subject, RESTRICTED membership, exact 64 human Actions, no deny/service Action, resource scopes and
canonical definition. Its effective state is `NONE`, `VERIFIED`, `STALE` or `REVOKED`. The Admin
membership response exposes only status, Role/catalog/membership/binding versions and update time;
Role UUID and both internal hashes never cross the HTTP boundary.

Generic assignment has a fixed `HUMAN_ROLE` discriminator in both its composite FK and CHECK. Role
assignment, identity provisioning, Role update and Role deactivation also reject Canonical Admin in
application code. The application database role has read-only binding access and no binding DML or
binding function execution. There is no production bind/rebind/revoke HTTP endpoint, UI or stored
procedure.

The sole automatic binding path is the parameter-free `bootstrap_local_identity()` command. It
checks `APP_ENV == "development"` before resolving secrets or opening a database, loads only the
fixed local Workspace/Subject from the database and verifies the exact current canonical human
envelope. The existing trusted bootstrap principal is privileged and may bypass RLS, so the
authoritative boundary is the command's pre-database environment guard and target-free helper.
Fixed-ID RLS policies remain defense in depth for non-bypassing execution; they are not presented as
a sandbox for that operator principal. Demo, seed, test, staging and production environments create
zero automatic bindings.

`admin.self_approve` remains `PENDING_PROTECTED_BINDING`. Revision `0089` records binding evidence
only: it does not change any maker/checker evaluator, allow same-subject approval or add an
operation-level exception. Those decisions remain A4c.

## Migration and rollback

The upgrade backfills one unassigned canonical definition for each existing Workspace and installs
the same trigger for future Workspaces. The 64-Action snapshot, catalog version and capability hash
are pinned; a source catalog drift stops migration/import rather than silently changing history.

Downgrade first restores the pre-0089 provisioning function. It refuses to proceed if any binding
row has ever been written or a canonical definition is referenced by assignment, assignment event
or data rule. Otherwise it removes the unassigned definitions, policies, trigger, table,
discriminator constraints and columns without deleting user, membership or custom-Role data.

## Consequences

- Canonical Admin is server-owned evidence, never a delegable custom Role.
- Existing production users are not promoted by migration, seed or reconciliation.
- A stale membership, Role/catalog version or access/resource-scope hash removes verified binding
  status without trusting browser state.
- The protected binding does not provide self-approval until a separate workflow-specific ADR and
  implementation are accepted.
