# ADR-0074: Unified Knowledge domains, pinned catalog Proposals and bounded upload ingress

- Status: Accepted
- Date: 2026-07-30
- Owners: Product, Security, Data Architecture, Knowledge Platform
- Refines: ADR-0069, ADR-0071, ADR-0072, ADR-0073

## Context

The Studio picker read `GET /knowledge/domains`, while its management dialog read and mutated a
second `/knowledge/domains/manage` surface. Both ultimately used
`catalog.vocabulary_entries(kind=DOMAIN)`, but separate browser state and response shapes allowed
the views to drift. The web Nginx edge also rejected multipart bodies above 2 MiB before the
approved 10 MiB interactive parser could apply its content controls.

Catalog search returned bounded summaries without field paths by design. The browser did not
resolve the selected summary through the authorized detail contract, leaving no fields to apply.
It also serialized catalog identity and fields into the general assistant prompt instead of asking
the server to prove the selected Asset, classification and exact source versions again.

React Flow nodes and edges were stored beside the typed T-Box element set. Semantic edge deletion
and unsaved node coordinates could therefore diverge from the hierarchy tree and safe editor.

## Decision

### One domain resource and one browser state

`GET /api/v1/knowledge/domains` returns the authorized active DOMAIN resources required by both
the Step 1 picker and management table, including nullable creator/time/version management
metadata and referenced Asset count. `POST /knowledge/domains` creates a managed domain and
`PATCH|DELETE /knowledge/domains/{domain_id}` rename or archive it. The old `/manage` paths remain
hidden compatibility aliases only.

All routes use the same PostgreSQL `catalog.vocabulary_entries` rows. The browser owns one
classification-scoped domain list, re-reads it after every mutation, and refuses to select a
created UUID absent from that authoritative response. ADR-0073 authorization is unchanged:
authors may create and immediately select their own managed domain; inventory-wide management,
rename and archive remain `admin.manage`.

### Bounded ingress

The web edge accepts 12 MiB on `/api/`, enough for the 10 MiB Studio document plus multipart
framing. The application parser and create-only Object Storage adapter keep the exact 10 MiB
limit, extension/MIME agreement, archive expansion bounds and parser protections from ADR-0072.
This is not an unlimited upload route.

### Pinned catalog and document Proposals

Catalog search uses the existing governed Catalog service and supports the same bounded searchable
metadata fields plus an exact domain filter. Selecting a summary resolves the authorized detail
before fields can be applied.

`POST .../tbox/catalog-proposals` accepts only a local Asset UUID, at most 100 server-returned field
paths, Proposal mode and target block. The server re-authorizes the Draft and source, proves every
field against the exact source version, builds the assistant input, and stores a source reference
containing the source/projection versions. Browser-authored provider prompts are not trusted.

Document and catalog model output pass through strict JSON schema and domain validation. One
deterministic correction pass may materialize only the already-defined `SUBCLASS_OF` default,
followed by an aggregate integrity pass. The source reference records those pass counts. No raw
Cypher is generated, executed against Neo4j, or returned to a model for self-healing. The UI
describes this approved typed-AST validation instead of claiming an executable Cypher loop.

### Graph projection state

The composed typed T-Box `elements` set is the semantic source for the hierarchy tree, React Flow
edges and safe editor. React Flow viewport, selection and coordinates remain presentation
metadata. Node movement is copied into element layout metadata before any semantic projection is
rebuilt, so adding a Class does not reset unsaved positions or zoom.

Loose body/border connection targets are allowed. A current-layer Class may start a Relationship
to a current or earlier-layer Class; an earlier read-only Class cannot start one. Hierarchy
semantics remain child `parent_stable_element_id`, while the canvas renders the visual edge from
the parent bottom to the child top. Edge reconnect/delete and tree label edits update the same
typed elements and safe text.

The Instance Management route remains the approved architectural entry point for future
Property-profile CRUD. This decision does not invent `tbox_property_profiles` storage or relax its
future RLS/ETag design gate.

## Consequences

- Picker, direct add and management dialog cannot maintain competing domain lists.
- Files between 2 MiB and 10 MiB reach the governed parser; larger files remain rejected.
- Catalog Proposal inputs are exact, authorized and version-pinned.
- Proposal progress can be based on returned validation evidence instead of timers or fake nodes.
- Tree, canvas and safe text update from one semantic state while layout remains stable.
- Existing domain ABAC and the no-raw-Cypher invariant remain intact.

## Verification

- Unified domain route/path and authoritative browser refresh tests.
- Nginx 12 MiB edge assertion plus 10 MiB parser/profile negative tests.
- Catalog filter/detail and exact-field Proposal contract tests.
- Typed Proposal correction/validation evidence positive and invalid-reference negatives.
- Graph hierarchy direction, Relationship list, loose connection, layout persistence and
  block-lock component/browser checks.
- Full Ruff, strict mypy, pytest, static verification, TypeScript, ESLint and production build.
