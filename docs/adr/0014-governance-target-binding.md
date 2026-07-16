# ADR-0014: Immutable governance target binding

- Status: Accepted
- Date: 2026-07-17

## Decision

Every newly created catalog-metadata change item is bound by the server to one currently authorized
local catalog projection row before the change aggregate is inserted. The immutable evidence stores
the local asset ID and type, DataHub URN, system/domain/owner scope, classification, lifecycle,
source version and observation time. A canonical hash covers the provider identity and the
authorization-relevant attributes. Source version and observation time remain separate evidence and
do not cause authorization-scope drift by themselves.

The browser cannot submit any binding field. Creation accepts exactly one allowlisted DataHub aspect
UPSERT, resolves its dataset URN through the authorization-pruned workspace projection and acquires a
PostgreSQL share lock on that projection row until the request transaction commits.

Point reads and lists re-resolve the current target and omit a request when the target is unavailable
to the caller. Review, approval, retry and user-controlled forward transitions also compare the
current authorization-relevant target fingerprint with the immutable binding and fail closed on
identity, classification, lifecycle or scope drift. The aggregate authorization decision retains the
requester/self-approval rule and uses the bound target scope; a grouped target decision uses current
attributes.

The binding does not have a foreign key to `catalog.assets_projection`. That table is a rebuildable
read model and must remain replaceable without deleting governance evidence. Runtime creation and
mutation paths instead compare workspace, local asset ID, external URN, type and current scope under
forced workspace RLS. The app role cannot update stored change items.

## Legacy quarantine

Migration `0015` deliberately does not backfill pre-existing items from the current projection. Such
a backfill would misrepresent present values as creation-time evidence. Binding columns therefore use
an all-or-none nullable shape: existing unbound rows remain auditable in PostgreSQL but are hidden
from ordinary list/detail access and cannot be approved, advanced or applied. Recovery requires an
explicitly governed re-proposal, not an inferred binding.

## Remaining gates

This decision does not claim atomic provider compare-and-set. The apply worker still requires a
separately approved least-privilege read capability to revalidate the current requester, target and
classification policy immediately before the provider call. It also needs provider/URN/aspect
serialization. A PostgreSQL advisory lock can serialize DataRiver workers only; DataHub UI,
ingestion and other writers do not share that lock. The current DataHub adapter has no conditional
write precondition, so before/after hashes remain detection and reconciliation rather than external
CAS. These remain production gates.
