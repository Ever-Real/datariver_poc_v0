# ADR-0125: Node POC exact Table ↔ System binding

- Status: Accepted for PHASE 1C-1
- Date: 2026-08-16
- Owners: Product, Application, Data, Frontend
- Supersedes for new administration: ADR-0109 schema-wide mapping
- Preserves: ADR-0109 historical Change Request routing evidence

## Context

The authoritative DEV runtime is the Node POC. Its existing access document is the sole application
User/Role/System authority and already provides versioned System master records, current user
responsibility assignments and CAS updates. It also contains a legacy
`(platform, database_name, schema_name) -> System` mapping that was introduced only for Change
Request routing.

The current product policy distinguishes four independent decisions:

1. Role/capability determines which action a user may perform.
2. Explicit Table grant determines which Table a non-admin may see.
3. Security grade constrains whether the Table may be disclosed by a feature.
4. Responsible System determines workflow responsibility; it is not Table read authority.

The first prerequisite is an exact N:M Table ↔ System master. Selecting a schema in the Admin UI is
only a filter/bulk-selection operation. It must not create an inheritable schema rule.

## Decision

PHASE 1C-1 keeps the existing access document as the System master and responsibility authority.
System `system_id` and `code` are stable. Updating name/description increments the System version.
Deleting from the UI means archive (`active=false`): dependent current assignments and legacy schema
scopes are deactivated, while historical identifiers and exact Table-binding rows are retained.

Exact Table ↔ System pairs are stored in one bounded `poc_state` CAS scope:

```text
scope = table-system-mappings-v1

table_identity  = exact DataHub dataset URN
system_id       = existing access-document System ID
active          = current pair state
version         = pair-local monotonic version
created/updated = server time and authenticated admin subject
reason          = bounded operator reason
```

The scope is not a second IAM or permission authority. It stores no role, capability, user grant,
responsibility or security policy. Only the exact admin route can write it, with current
`admin.manage`, same-origin/CSRF checks, current active System validation, current DataHub `TABLE`
identity validation and `If-Match` CAS. Inactive rows are retained as lifecycle evidence. The
existing `poc_state` transaction/advisory-lock implementation provides the same atomic CAS semantics
without a new table or migration.

The Admin mapping UI supports search, schema/System/security-grade filters, checkboxes, Shift range
selection, current-filtered-result selection, multiple System selection, assign and remove. Bulk
selection persists only the selected exact Table URNs; future Tables in the same schema inherit
nothing.

Table grade shown in this slice is derived for presentation by exact normalized equality against
DataHub tag identity/name `restricted` and `credential`, with `credential` precedence and `normal`
otherwise. Substring matching is forbidden. The current catalog projection now retains Table tag
URN/name references. Grade and grant enforcement are intentionally deferred to PHASE 1C-2/1D.

## Compatibility

- Legacy `system_schema_scopes` rows remain readable for historical CR routing and are not silently
  converted or deleted.
- Current Catalog/read filtering still uses the previous policy until explicit User ↔ Table grants
  and grade enforcement are implemented. PHASE 1C-1 must not claim the latest end-to-end data policy.
- Current CR records and approval hashes are unchanged.
- FastAPI/Keycloak/OIDC/workspace are not introduced into the Node runtime.

## Consequences and follow-up

- PHASE 1C-1 can be rolled back by reverting the source/image. The new scope is additive and ignored
  by the prior runtime; exact rows remain recoverable.
- Whole-document CAS is intentionally bounded. A measured scale/contestion problem may justify a
  normalized storage adapter later, but it may not become a second System or authorization authority.
- PHASE 1C-2 must add explicit User ↔ Table grants and user security grade without putting large
  grant sets into the access document.
- PHASE 1C-4 must migrate CR responsibility to one exact mapped System while preserving historical
  schema-based receipts.
- PHASE 1D must filter before count/ranking/context/traversal, including vector and graph paths.
