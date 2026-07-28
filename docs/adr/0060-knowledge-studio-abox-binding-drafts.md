# ADR-0060: Knowledge Studio A-Box binding drafts

- Status: Accepted
- Date: 2026-07-28
- Owners: Product, Data Architecture, Security, Knowledge Platform
- Refines: ADR-0058, ADR-0059

## Context

Data Enricher must connect accepted T-Box elements to physical Dataset fields without placing
source rows in a graph, changing a released ontology, exposing provider identifiers, or turning a
browser form into canonical mapping state. The current Studio aggregate stores only Step 1 state.
Putting arbitrary mapping JSON on `studio_drafts` would remove referential checks, make partial
updates overwrite unrelated work and prevent immutable source-version evidence.

DataHub is a fallible external metadata provider. Dataset discovery must remain fast and scoped to
the current Workspace, classification policy, systems and domains. A selected Dataset still needs a
fresh, bounded field contract before a mapping can be persisted.

## Decision

1. Accepted T-Box Class, Property and Relation elements are exposed to A-Box through a typed
   `tbox_draft_elements` index keyed by Draft and stable element ID. It is a projection of accepted
   typed operations, not a second schema truth. Data Enricher never mutates these rows.
2. A physical source pin is an immutable `source_references` row. The first supported contract is
   `CATALOG_DATASET`, containing only a local catalog Asset UUID, exact detailed provider-schema
   version, exact authorization-pruned catalog-projection version, classification, a bounded typed
   selection document and its canonical hash. External URNs, endpoints, credentials and raw
   provider documents are not stored or returned.
3. Mutable Step 3 state is normalized into `abox_binding_drafts` and
   `abox_mapping_rule_drafts`. One Draft target has at most one current binding. Rules accept only
   `SUBJECT_ID`, `PROPERTY`, `EDGE_LINK` or `EDGE_PROPERTY`; the first UI increment writes Class
   `SUBJECT_ID`/`PROPERTY` rules with the server-owned `IDENTITY` transform.
4. Mapping updates require `Idempotency-Key` and exact `If-Match`. The repository locks the Studio
   Draft, checks its version, revalidates the target element, local projection
   version/classification and server-returned field paths, replaces only that target's rule set,
   increments both Binding and Draft versions and commits the exact response snapshot atomically.
   The detailed provider-schema version is pinned for later ingestion-time revalidation. A stale
   Draft returns `412`.
5. Dataset search uses the authorization-pruned local DataHub catalog projection with bounded
   keyset pagination. Selecting a Dataset resolves its bounded field detail through the existing
   Catalog service, which applies Catalog authorization and the DataHub Gateway/cache/stale policy.
   The browser cannot send a DataHub query, URN or provider endpoint.
6. A node's `Mapped` visual state means only that at least one persisted Draft rule exists.
   `DRAFT/VALIDATED/STALE` mapping readiness and ingestion status remain separate. This increment
   does not create a graph, ontology version, release, Neo4j projection, DataHub mutation or
   ingestion job.

## Consequences

- `studio_drafts` remains the optimistic-concurrency fence for the whole authoring aggregate while
  child rows preserve source/rule referential structure.
- Binding edits cannot damage accepted T-Box content because their route and repository have no
  T-Box write operation.
- Provider unavailability may make fresh field selection unavailable; the API fails honestly
  instead of accepting a field path the server did not return.
- Immutable binding versions, validation evidence and ingestion jobs remain separate later
  increments. A Draft `Mapped` badge must not be presented as validated, ingested or published.
- A CREATE Draft without accepted T-Box elements renders an explicit empty/unavailable state. The
  API does not invent placeholder classes or properties.

## Verification

- Model/migration/data-model parity, FORCE RLS, composite Workspace foreign keys and least privilege.
- Bounded authorized Dataset search, provider field normalization and no provider identifier leak.
- Rule vocabulary, target ownership/kind, field allowlist, source-version/classification and stale
  ETag negative tests.
- Idempotent replay, changed-request rejection and proof that only A-Box child rows plus Draft
  version/timestamp change.
- React Flow selection, Binding Panel mapping, persisted `Mapped` badge and error/empty states.
