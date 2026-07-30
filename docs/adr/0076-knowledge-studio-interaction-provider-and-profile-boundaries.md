# ADR-0076: Knowledge Studio interaction, provider grammar and profile boundaries

- Status: Accepted
- Date: 2026-07-30
- Owners: Product, Data Architecture, Knowledge Platform
- Refines: ADR-0069, ADR-0070, ADR-0071, ADR-0074

## Context

Knowledge Studio needs direct graph manipulation without weakening the layer dependency rules.
Users must be able to start a Relationship at either the active or an earlier Class and finish it
on the other Class, while an earlier block remains immutable. `SUBCLASS_OF` must be visible and
editable with ordinary Relationships without creating a second canonical representation beside a
Class parent.

The development OpenAI-compatible provider accepts a bounded JSON grammar but rejects Pydantic
schemas containing definitions, references, nullable unions and validation annotations. The
provider returned HTTP 400 while the application surfaced the dependency failure as 502. The
model output still requires the full application-side Pydantic and aggregate validation.

Deleting the newest block also failed before the business rule was reached because generated
idempotency operation names exceeded the persistence column's 100-character bound. Retained
Proposal evidence referenced the block through an optional target and must survive deletion.

Domain administration and future Property profiles have different lifecycle and authority
boundaries. They must not remain controls inside the Studio authoring form or be represented by
unapproved mock CRUD.

## Decision

### Active-layer Relationship ownership

Every new Relationship is owned by the active block. Either endpoint may be an active Class or a
Class from an earlier block, and either endpoint may be the source. At least one endpoint must
belong to the active block. Both endpoints must be owned by the active block or an earlier block.

Earlier Classes remain grouped and read-only for name, Property, position and deletion. Existing
earlier Relationships remain immutable. Allowing an earlier Class to be a connection source does
not transfer its ownership and does not mutate the earlier block.

The canvas exposes border source regions and a whole-node target while a connection is active.
Stored edges use deterministic side handles derived from current endpoint positions and render a
curved, directed path. Canvas node positions and viewport are presentation state copied into the
typed element layout metadata; semantic updates reuse them rather than relaying out the graph.

### One canonical hierarchy

`tbox_classes.parent_stable_class_id` and `hierarchy_relation` remain the canonical hierarchy
representation from ADR-0070. The tree, canvas and Relationships list derive a virtual relationship
from those fields. Renaming a normal active-layer Relationship to `SUBCLASS_OF` removes that
Relationship element and assigns the source Class parent to the target Class after ownership,
single-parent and cycle checks. Deleting the derived relationship clears the parent fields. No
duplicate `tbox_relationships` row is created.

### Provider grammar normalization

The OpenAI-compatible adapter transforms the trusted Pydantic output schema into a bounded provider
grammar schema by resolving local definitions, reducing nullable primitive unions and dropping
provider-unsupported annotation and bound keywords. The structural object, array, primitive,
required, enum and `additionalProperties` constraints remain.

The provider grammar is an output-shaping aid, not validation authority. The original Pydantic
model, allowed data-type vocabulary, typed T-Box element validation and aggregate integrity pass
remain mandatory after generation. Raw Cypher is neither generated nor executed.

### Latest-block deletion and idempotency

Internal operation names must fit the persisted 100-character operation bound for maximum UUID
inputs. New short `kg.*` namespaces are used while request hashes retain resource identity.

Only the maximum-ordinal block may be deleted. Proposals targeting that block are retained as
evidence: their optional target is cleared and the retired block ID and timestamp are appended to
the proposal source reference under the same transaction and ETag fence. The block and its
normalized Class, Property and Relationship rows can then be deleted without losing Proposal
history.

### Information and profile workspaces

The Knowledge menu has independent first-depth routes:

- **조회 및 생성** for Registry and Studio entry;
- **정보 관리** for the existing canonical Domain CRUD;
- **인스턴스 관리** as the future Property-profile and A-Box management boundary;
- **Chat Test** for the isolated GraphRAG test surface.

The Basic Information step consumes the Domain resource but does not host its administration
control.

The Instance Management route is an architecture entry point only until its aggregate is approved.
The proposed page uses an Asset/Release selector with tabs for Property Profiles, A-Box Bindings
and Projection Sync. A future profile aggregate should reference a released Property URN and keep
unit, description, profile version and ETag in a profile table, keep synonyms in a normalized
child table, and publish projection work through an outbox. It requires workspace RLS, typed
create/update/archive operations and no direct Neo4j mutation. This ADR does not create those
tables or claim CRUD that does not exist.

## Consequences

- Users can connect active and earlier Classes in either semantic direction without unlocking old
  topology.
- Hierarchy is visible alongside Relationships while PostgreSQL retains one canonical parent.
- Node and viewport positions remain stable across Class and Relationship edits.
- The approved local provider can produce typed Proposal output without relaxing post-generation
  validation.
- Latest-block deletion reaches the intended business rule and preserves Proposal audit evidence.
- Domain administration is centralized and the future profile boundary remains explicit rather
  than simulated.

## Verification

- Component tests cover persisted block-title feedback, historical layer locking, hierarchy
  projection, Unicode Property CRUD, stable typed text and maximum-ordinal block deletion.
- Provider adapter tests inspect the normalized grammar and revalidate output with the original
  Pydantic model.
- Persistence tests constrain idempotency operation names to the database bound.
- Full Ruff, strict mypy, pytest, static verification, TypeScript, ESLint and production build.
