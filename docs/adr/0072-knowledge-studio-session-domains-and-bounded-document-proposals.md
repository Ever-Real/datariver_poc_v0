# ADR-0072: Knowledge Studio session continuity, managed domains and bounded document Proposals

- Status: Accepted
- Date: 2026-07-29
- Owners: Product, Data Architecture, Security, Knowledge Platform
- Refines: ADR-0058, ADR-0059, ADR-0069, ADR-0071

## Context

Knowledge Studio authors move repeatedly between Basic, Graph Builder and Data Enricher and between
several T-Box layers. React component-local state discarded a valid but not-yet-saved canvas,
safe-Cypher buffer and viewport when one of those views unmounted. The Basic contract also exposed
one endpoint alias and a read-only domain picker even though operators need several resolvable
aliases and governed workspace domain administration.

ADR-0071 kept document analysis closed until a durable worker existed. The product now requires a
bounded interactive document-to-Proposal path for authoring, while full A-Box ingestion and large
document analysis remain durable jobs. A filename-derived or timer-derived fake Proposal is still
prohibited.

## Decision

### Session continuity and canonical ownership

A draft-keyed Zustand store retains only in-memory authoring state: current UI step, unsaved Basic
values, selected layer, typed elements, the safe-Cypher buffer and React Flow viewport. The A-Box
session also retains the selected target/source, source query, subject/property mapping fields,
preview focus and unfinished reviewer reason. Each T-Box layer has an independent snapshot.
Switching layers composes every layer snapshot, groups non-active layers read-only and keeps the
active layer editable. Switching steps may unmount a component, but does not discard its snapshot.

The store is not a second canonical database and is deliberately not placed in localStorage or
sessionStorage. PostgreSQL, ETag-fenced Typed Operations and the existing origin-scoped IndexedDB
Basic recovery queue retain their ADR-0059 authority. A server refresh rehydrates the canonical
Draft; an in-memory edit is accepted only through the existing version fence.

### Endpoint aliases and managed domains

`knowledge.studio_drafts.endpoint_aliases` is a bounded JSON array of one to ten validated aliases.
The first value must equal the existing `endpoint_alias` and remains the canonical immutable
`knowledge.graphs.slug` on publication. Every alias is checked against live Draft arrays and
materialized graph slugs under a workspace/alias transaction advisory lock. Additional aliases are
Draft contract data in this increment; provider routing activation is a separate release decision.

Workspace-managed domains reuse `catalog.vocabulary_entries`, because that table is already the
canonical typed DOMAIN resolver. Managed rows carry an optional membership-bound creator and an
optimistic-lock version. Create, rename and archive are `admin.manage` operations with
idempotency/ETag fences. Archive preserves existing Asset foreign keys and removes the domain from
new selection. DataHub reconciliation cannot inactivate `urn:li:domain:datariver-*` rows.

### Bounded interactive document Proposal

The interactive path accepts PDF, CSV, UTF-8 TXT, XLSX, DOCX, PPTX, HTML, XML and JSON up to
10 MiB. DOC and XLS remain rejected. The API validates filename/extension/MIME together, rejects
binary text, DTD/entity XML, macro/executable/external OpenXML members, excessive archive entries
and excessive expanded bytes. Extracted text is capped before inference.

After Draft ownership, `kg.edit`, TBOX step and ETag validation, the original bytes are written
create-only to the configured filefolder Object Storage bucket. The prompt treats the excerpt as
untrusted data and invokes only the approved Schema Assistant binding. The result is an immutable,
typed Proposal with an exact bucket/key/upload/hash source reference. Before acceptance, an author
may exclude a proposed element or edit its bounded name and Property type in the canvas overlay.
The apply request carries those typed overrides; the server proves that every override belongs to
that exact Proposal, preserves stable identity and revalidates the complete T-Box aggregate. The
Proposal cannot mutate the Draft until explicit Keep Original/conflict resolution and an
idempotent ETag-fenced apply.

The browser stepper reflects the real request boundary: queued stages remain pending while the
server parses, extracts and validates; all stages become complete only after a typed Proposal
response. No timer, filename heuristic or fabricated nodes claim backend progress.

This bounded authoring route does not replace ADR-0069 durable workers. Large/full extraction,
A-Box ingestion, retries, progress ledgers and vector embedding remain background jobs.

### Lightweight T-Box and future Instance management

Graph Builder continues to own only Class/Relationship topology and lightweight Property name/type
fields. A new Knowledge Instance Management route is the explicit future home for synonym, unit,
profile and other URN-referenced detail. The empty route does not fabricate a profile aggregate or
write contract.

## Consequences

- Layer and step navigation no longer destroys unsaved in-memory canvas/editor/viewport or A-Box
  mapping-form state.
- Canvas, hierarchy tree and safe-Cypher text derive from one layer-composed authoring state.
- Domain administration is auditable and version-fenced without introducing a competing master.
- Multiple aliases round-trip through API and PostgreSQL while publication keeps one canonical slug.
- Interactive document authoring is real and bounded; durable ingestion capability claims remain
  unchanged.
- Create-only document bytes can exist before provider inference completes. Object lifecycle and
  orphan reconciliation use the configured filefolder retention/operations boundary and remain a
  target-environment operations gate.

## Verification

- Zustand layer/step restoration, invalid-editor retention and selected viewport tests.
- Alias parsing, duplicate/shape validation and Draft ETag tests.
- Managed-domain authorization, idempotency, version and archive tests.
- Document allowlist, Unicode extraction, XML entity and OpenXML executable/expansion negatives.
- Proposal override membership, Unicode-name and Property-only data-type validation.
- React Flow initial zoom, tree drop-target, direct delete, grouped-layer and lock interaction tests.
- SQLAlchemy, additive `0066`, regenerated canonical `0001` and data-model agreement.
- Strict backend/frontend gates and authenticated browser DOM verification.
