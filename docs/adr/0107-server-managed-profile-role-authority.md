# ADR-0107: Server-managed profile Role authority

- Status: Accepted
- Date: 2026-08-01
- Refines: ADR-0024, ADR-0027, ADR-0103, ADR-0106

## Context

Business job functions, administrator-created Access Roles and the product-facing account profile
have different meanings. Inferring authority from `job_function`, a browser label or an editable
Role would make revocation unreliable. Reusing a full Access Role for the four product tiers would
also mix action bundles with clearance and resource scopes. The product requires a simple
Viewer/Engineer-Steward/Manager/Admin selector while retaining server-side authorization, explicit
denies, classification clearance, RLS and System responsibility scope.

## Decision

`PROFILE_ROLE_POLICY_V1` is the single server-owned action policy. Viewer includes the common
read surfaces, including `change.read`. Engineer/Steward inherits Viewer and adds registration,
change and quality mutations whose resource authorization is constrained by current active System
responsibility. Manager inherits Engineer/Steward and adds Knowledge and Governance
read/create/edit/review/archive; publish and activate are excluded. Admin is the existing
Canonical Admin 64-human-Action envelope and excludes the five service-principal-only Actions.
Lifecycle removal means the service's archive, cancel, revoke or deactivate operation with retained
history; no generic hard-delete Action is introduced.

Revision `0090` creates `iam.profile_role_assignments` for only `VIEWER`,
`ENGINEER_STEWARD` and `MANAGER`, plus append-only assignment events. The assignment stores the
server policy version and materialized Action hash. Admin is never stored as a profile assignment;
it is derived only from current VERIFIED `iam.canonical_admin_bindings` evidence. Existing humans
remain `UNASSIGNED` and retain their legacy membership authority until an explicit transition.
There is no job-function inference or migration-time user promotion.

New human provisioning rejects a non-null compatibility `role_id` before the identity provider is
called, creates a Viewer assignment and a CONFIDENTIAL membership atomically, and creates no
service assignment. An explicit non-Admin profile transition atomically materializes the exact
Action bundle, floors the target's clearance to CONFIDENTIAL while preserving RESTRICTED, removes
any active custom-Role evidence, and appends audit/outbox evidence correlated by the non-null
authorization decision ID. A profile-bound membership may
subsequently change clearance through the governed access command, but tier changes do not accept
or infer clearance from the client.

The inverse transition to a custom Access Role is not an implicit union: the generic path rejects
an active profile assignment until a separate governed removal is part of the same transaction.
Malformed, stale, revoked, hash-mismatched, policy-mismatched or membership-version-mismatched
profile evidence yields no profile Actions. Existing membership `denied_actions` always subtracts
from the bundle.

Engineer/Steward, Manager and Admin System scope is hydrated on every request from current active
Developer/Data Steward responsibility joined to an active System. It is never copied into the
membership JSON and never unioned with a stale stored System list. Viewer is not assignable to a
System. The current slice does not create a System-to-schema/table binding model.

Canonical Admin promotion/demotion uses a separate command. The actor must be a different current
VERIFIED Canonical Admin, the target must be an active human, assurance must be fresh hardware
WebAuthn, and reason, `If-Match`, binding version and idempotency are mandatory. Self-transition,
service identities and demotion of the last VERIFIED Admin are rejected. This refines ADR-0106 only
for that governed production transition; generic Role/provisioning paths still structurally reject
Canonical Admin. It does not enable workflow self-approval, which remains closed for A4c.

The protected database function independently revalidates the actor binding's exact Canonical Role
ID/version, capability catalog version/hash, active human membership version and fixed Canonical
Role document. The membership must carry the exact Admin Action, deny and empty System-scope
documents, include `security-administrators`, and exclude service-account and custom-Role markers;
unrelated non-authority groups remain valid. Its last-Admin guard counts only bindings that satisfy
that same current tuple. A revoked binding may be re-promoted only at its current binding version;
a subject without binding history must use expected version zero.

## Migration and rollback

The upgrade adds the two profile tables, governed functions and the Viewer provisioning contract.
It creates no assignment or binding for an existing user and performs no blanket clearance update.
The downgrade restores the previous provisioning contract and refuses to discard any profile or
governed Admin history. Subject, membership and custom-Role rows are never deleted.

## Consequences

- The dropdown is a presentation of server evidence, not a client authorization source.
- Profile Actions, per-user clearance and System responsibility remain distinct canonical inputs.
- Removing a responsibility or downgrading/revoking profile evidence changes the next hydrated
  request without relying on browser cache.
- Schema/table-level System catalog binding and workflow self-approval remain separate work.
