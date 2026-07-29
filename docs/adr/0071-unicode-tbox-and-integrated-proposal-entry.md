# ADR-0071: Unicode T-Box identifiers and integrated Proposal entry

- Status: Accepted
- Date: 2026-07-29
- Owners: Product, Data Architecture, Security, Knowledge Platform
- Refines: ADR-0069, ADR-0070

## Context

Korean Class and Property names were destructively reduced by an ASCII-only browser normalizer and
then rejected by the HTTP/domain contracts. The hierarchy tree also displayed only an implied
`SUBCLASS_OF`, while authors need a visible, editable semantic name on the parent edge. The Graph
Builder exposed separate block kinds for document, catalog and direct entry even though all
machine-derived schema must pass through the same Proposal review and typed-operation acceptance.

Document parsing is still subject to ADR-0069's separately fenced durable worker. Enabling a file
picker without that worker would either process untrusted documents in the browser/API process or
pretend that a filename is analyzed. Neither is an acceptable implementation.

## Decision

### Unicode identifier contract

Canonical Class, Property and Relationship names use NFC-normalized Unicode. The first code point
must be a Unicode letter; subsequent code points may be Unicode letters, numbers or underscore.
Display names remain separately bounded human text. Stable element IDs, endpoint aliases, data
types, provider identities and idempotency keys keep their existing narrower contracts.

The browser normalizer, safe schema-Cypher lexer/parser, Pydantic boundary, LLM typed response and
domain validator share this rule. No raw Cypher is executed. Invalid or non-NFC input is rejected
before persistence, while Korean labels round-trip without transliteration.

### Named canonical hierarchy edge

`tbox_classes.parent_stable_class_id` remains the single parent and cycle-detection truth.
`hierarchy_relation` is a bounded semantic label on that parent edge and defaults to
`SUBCLASS_OF`. It is not a duplicate `tbox_relationships` row. Re-parenting, relation-label edits,
safe-editor round trips and later-layer locks update or compare the Class aggregate atomically.

The parent lookup index is `(workspace_id, draft_id, parent_stable_class_id, stable_class_id)`.
It supports bounded child expansion and recursive CTE traversal without a second hierarchy store.

### Integrated authoring entry

Every new authoring layer is a `DIRECT` layer. Its toolbar provides direct editing, governed
catalog selection and the document Proposal entry. Catalog search is a dedicated T-Box read
contract: it applies the same Draft ownership, `KG_EDIT`, domain/classification and provider
authorization as A-Box source selection, but is available only in the TBOX step. Selected field
paths and exact source/projection versions become bounded assistant input; model output remains a
typed, immutable Proposal.

Proposal creation no longer auto-applies a conflict-free response. The canvas shows a review
overlay, authors may exclude proposed elements, and acceptance remains one-time, idempotent and
ETag-fenced. Exclusion is allowlisted to stable IDs from that exact Proposal and the remaining
aggregate must pass the same shape, hierarchy and layer-dependency validators.

PDF, DOCX and XLSX remain visible as the supported document profiles, but upload is fail-closed
until the ADR-0069 durable parser/model Proposal worker is deployed. The UI reports that capability
state explicitly and makes no upload or inference request. DOC and XLS remain unsupported.

### Validation authority and future Property profiles

Cypher integrity is checked in the background by the deterministic safe-subset parser and the
server typed aggregate validator. LLM output may suggest or review schema only through Proposal;
it cannot certify syntax or mutate canonical data. This deliberately rejects an LLM-as-validator
authority because model availability and output are non-deterministic.

Graph Builder owns only Property name, data type and current lightweight policy fields. Existing
opaque metadata reference ID/URN slots remain the extension point for a later
`tbox_property_profiles` aggregate. No profile table or lifecycle is fabricated in this increment.

## Consequences

- Korean identifiers remain stable across tree, canvas, safe text, API and PostgreSQL.
- A hierarchy edge label is editable without creating competing parent and Relationship facts.
- Property create/update/delete uses the same block-owned Typed Operation save as Class changes.
- Prior layers remain grouped and read-only, later references keep historical elements locked, and
  only the newest block can be deleted.
- Catalog-driven inference is usable through the existing governed assistant runtime.
- Document inference remains honestly unavailable until its durable worker and security tests pass.

## Verification

- Unicode NFC domain and safe-parser positive/negative tests.
- Tree sibling drag/drop, hierarchy-label edit and safe-text round trip.
- Name-click-only floating editor, Property create/update/delete and multi-side handles.
- Proposal preview/exclusion and exact-ID negative tests.
- TBOX-step catalog authorization/classification negatives.
- SQLAlchemy, additive `0065`, canonical `0001` and data-model deterministic agreement.
- Strict backend/frontend gates and authenticated browser DOM verification.
