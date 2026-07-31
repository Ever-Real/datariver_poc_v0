# ADR-0096: Knowledge source media vocabulary and Asset Release pins

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Data Architecture, Knowledge Platform, Application, Security Architecture
- Refines: ADR-0044, ADR-0058, ADR-0074, ADR-0092, ADR-0093

## Context

ADR-0093 expanded the durable Knowledge source-analysis worker from PDF to a bounded modern
document vocabulary. The application accepted those formats, but
`knowledge.source_snapshots` retained its historical PDF-only database constraint. A valid
non-PDF upload could therefore pass integrity and parser validation and then fail while the
immutable source snapshot was inserted.

The Studio design also reserves `ASSET_RELEASE` blocks for attaching another Knowledge Asset.
The source identity for that operation must not be inferred from an alias, mutable active pointer
or browser-supplied schema document.

## Decision

### Immutable document MIME vocabulary

Revision `0082` replaces the PDF-only source-snapshot constraint with the exact canonical MIME
vocabulary owned by `domain.knowledge_pipeline.KNOWLEDGE_SOURCE_MEDIA_TYPES`:

- PDF;
- UTF-8 CSV and plain text;
- JSON;
- XML without DTD or entity declarations;
- HTML and XHTML text;
- macro-free DOCX, XLSX and PPTX OpenXML packages.

Legacy DOC/XLS/PPT, macro-enabled OpenXML MIME values, generic binary MIME and every value outside
that allowlist remain invalid. The database constraint records canonical media identity; it does
not inspect package bytes. Filename/media agreement, macro and external-link rejection, XML
safety, integrity hash and size checks remain prerequisites of the accepted upload and bounded
parser contract. Only that verified manifest may be bound to a source snapshot.

The migration is additive for every existing PDF row. A downgrade is refused while any non-PDF
source snapshot exists, so rollback cannot silently discard or misclassify governed evidence.

### Exact Studio Release attachment

An `ASSET_RELEASE` T-Box input will pin the selected source Asset's local graph ID, exact immutable
Studio Release ID and exact T-Box hash. It must not pin an endpoint alias, a mutable
`active_studio_release_id`, an Instance Release ID or browser-authored schema content.

The server authorizes `kg.read` against the source Asset and its Workspace, Domain and
Classification scope when the candidate is selected. It repeats the same authorization and
graph/Studio-Release/hash ownership checks when the Proposal is applied and when the consuming
Studio Draft is published. Revocation, archival, cross-Workspace identity, release mismatch or
hash mismatch fails closed without changing accepted T-Box operations. The attachment creates a
typed Proposal and uses the existing explicit conflict-resolution path; it never rewrites the
source Studio Release.

The accompanying implementation uses the existing typed T-Box Proposal aggregate rather than a
second mutable source table. Its Proposal source document stores only the exact local graph,
Studio Release and contract hashes; the public response removes private object-store coordinates.
Draft-scoped ports, services and APIs perform selection, apply, review-submission and publication
revalidation without sending the source schema through an LLM.

## Consequences

- Every media type admitted by durable Knowledge source analysis is now representable in its
  immutable PostgreSQL source snapshot.
- The database continues to reject legacy, macro-enabled and ambiguous binary media identities.
- Existing PDF snapshots and jobs remain compatible.
- Modern package and XML safety are not duplicated as unverifiable SQL checks; they remain pinned
  to the integrity-verified upload/parser evidence.
- Asset attachment remains PostgreSQL-canonical, exact-versioned and authorization scoped instead
  of following a mutable active pointer.

## Verification

- Metadata tests compare the ORM and revision `0082` vocabulary with the domain allowlist.
- PostgreSQL persistence tests insert every approved MIME and reject legacy, macro-enabled and
  generic binary MIME values under the database CHECK.
- Existing parser and upload tests continue to prove macro-free OpenXML, XML entity rejection,
  extension/media agreement, size bounds and content integrity.
- Asset Release implementation tests cover draft-scoped authorization, SQL Workspace/Domain/
  classification/archive predicates, exact release ownership and aggregate T-Box hash read-back,
  stale hash rejection and access revocation before review/publication.
