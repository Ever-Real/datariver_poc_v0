# ADR-0086: Development administrator active Catalog scope reconciliation

- Status: Accepted
- Date: 2026-07-31
- Owners: Application, Security Architecture, Operations
- Refines: ADR-0011, ADR-0020, ADR-0024

## Context

The local development administrator has `RESTRICTED` clearance, the
`security-administrators` group and the required Catalog, Quality, Knowledge and Chat Actions.
Catalog projection synchronization, however, derives exact System and Domain UUIDs from governed
DataHub references after the local identity bootstrap has run. The bootstrap therefore cannot
materialize those future UUIDs in the administrator membership.

The Catalog screen can still show every same-Workspace non-deleted projection through ADR-0020's
audited quarantine-review exception. Quality, Knowledge data use and Chat correctly continue to use
ordinary classification, lifecycle, System and Domain ABAC. With no synchronized System/Domain
scope, those surfaces can consequently return only a PUBLIC asset even when many classified ACTIVE
assets exist.

Treating the administrator label as a portable superuser flag would violate ADR-0011, make
RESTRICTED Chat possible by accident and erase the distinction between a quarantined projection
and an authorized data source.

## Decision

After a successful development Catalog synchronization, reconcile the fixed local administrator's
membership with the exact non-null System and Domain UUIDs observed on same-Workspace,
non-deleted, `ACTIVE` Catalog projections.

The reconciliation:

- runs only when `APP_ENV=development` and targets the fixed local Workspace and administrator;
- preserves the existing clearance, groups, Actions, explicit denies and previously assigned
  scopes, adding only the exact currently observed Catalog System/Domain UUIDs;
- rejects a non-PUBLIC `ACTIVE` projection that lacks either governed scope;
- uses the existing version-fenced administrator membership service, an independent eligible local
  checker, a development-only password assurance exception and the normal policy decision,
  idempotency and outbox audit evidence;
- is invoked by the fresh-setup workflow after its first Catalog sync and by the update workflow
  after a Catalog sync or local-identity reapplication.

This is not a wildcard grant. Classification policy, explicit RESTRICTED Search grants, lifecycle,
workspace RLS, resource authorization and route-specific Actions remain authoritative.
`QUARANTINED` projections are counted and reported but are never added to a data-use exception.
ADR-0020 remains their only administrator observation path. `RESTRICTED` Chat remains denied.

## Consequences

- The local administrator can use every currently ACTIVE, governed Catalog table allowed by the
  active classification policy in Quality, Knowledge and Chat without manually copying provider-
  derived UUIDs.
- A later Catalog sync deterministically adds newly observed ACTIVE scopes and advances the
  membership version only when the effective scope changes.
- Unclassified or incompletely governed DataHub assets remain unavailable to Quality execution,
  Knowledge ingestion and Chat until their classification and Domain/System metadata are remediated.
- Production and enterprise identity onboarding retain explicit Role/membership assignment; this
  development reconciliation cannot run there.

## Verification

- Unit tests prove the command adds exact System/Domain IDs while preserving Actions, denies,
  groups and clearance.
- Workflow tests prove both fresh setup and update invoke the reconciler after Catalog sync.
- Runtime acceptance compares projection state with the administrator membership and proves:
  ACTIVE governed assets become visible to standard ABAC readers, quarantined assets remain absent
  from those readers, and the Catalog quarantine-review path remains independently audited.
