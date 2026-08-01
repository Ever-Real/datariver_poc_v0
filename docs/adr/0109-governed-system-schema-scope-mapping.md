# ADR-0109: Governed System schema-scope mapping for Change targets

- Status: Accepted
- Date: 2026-08-02
- Refines: ADR-0022, ADR-0107

## Context

Change Requests are routed through the canonical business System selected by the requester. Some
active DataHub table, view and dataset projections do not carry that business-System identifier,
although the existing `platform.system_schema_scopes` relation can associate their canonical
platform/database/schema locator with one System. A browser-authored locator or a direct
`AssetProjection.system_id` rewrite would create a second, unaudited authority and could silently
change Catalog, Knowledge, Quality or Chat behavior.

## Decision

The Admin Systems screen exposes a governed schema-wide mapping. An administrator selects an
authorized active TABLE, VIEW or DATASET asset ID; the server reads its canonical
platform/database/schema locator and creates, reactivates or deactivates the existing scope row.
The UI states explicitly that selecting one table connects its entire schema. It never sends or
claims a table-level binding and never changes DataHub or the Catalog projection.

Reads and candidates require an eligible human with a current VERIFIED Canonical Admin binding.
Mutation additionally requires `admin.manage`, the deployment's existing assurance policy, a
quoted System-version `If-Match`, `Idempotency-Key` and a bounded reason. The repository locks the
active System, selected assets and scope rows. Scope changes, the System version bump, policy
decision, audit/outbox and idempotency receipt commit in one transaction. A current mapping owned
by another System returns conflict; there is no silent reassignment.

Candidate and mutation validation use the same server-derived actor scope. PUBLIC needs only the
active Workspace asset boundary. INTERNAL and CONFIDENTIAL additionally require subject clearance
and an actual asset Domain in the actor's current allowed Domains. RESTRICTED mappings are closed
in this version pending an explicit-grant-aware design. The client cannot supply clearance, Domain
or a provider locator, and the mutation rechecks the selected asset under a share lock.

Only the Change target adapter resolves an effective routing System. Its SQL predicate accepts an
active mapped schema when the native projection System is absent or equal, or retains an active
native System when no scope row exists. A native/mapped conflict, inactive mapping/System,
incomplete or drifted locator, wrong Workspace or missing current responsibility fails closed.
Search, detail, intake and final reauthorization use the same CR-only reader, and the existing
target binding hash includes the effective System. Removing or changing the mapping therefore
invalidates the target on the next request.

## Exclusions

Generic Catalog presentation and its workspace-discovery mode, Registration, Knowledge, Quality,
Chat and Catalog description mutation retain their existing readers and scope policy. This change
adds no table-level mapping, DDL, migration, Action, DataHub write or AssetProjection mutation.
Existing manually routed CR targets continue to use their active native System when no schema
scope exists.

## Consequences

- The mapping is authoritative only for CR routing and uses an existing canonical relation.
- Operator-visible changes are version fenced, idempotent and auditable without exposing a
  browser-controlled provider locator.
- Mapping removal, reassignment, native conflict and locator drift revoke future CR target use
  instead of preserving stale access.
