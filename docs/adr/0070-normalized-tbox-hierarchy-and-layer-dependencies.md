# ADR-0070: Normalized T-Box hierarchy and forward-only layer dependencies

- Status: Accepted
- Date: 2026-07-29
- Owners: Product, Data Architecture, Security, Knowledge Platform
- Refines: ADR-0058, ADR-0059, ADR-0062, ADR-0069

## Context

The Graph Builder edits schema concepts, not instance entities. The folded
`tbox_draft_elements` row shape was sufficient for the first typed-operation increment, but it
mixed Class hierarchy, Property ownership and Relationship endpoints in nullable columns. It also
did not make cross-layer dependency locks explicit enough for a hierarchy tree and accumulated
read-only groups.

Authors need to add and re-parent Classes in a tree, edit the active layer while seeing every other
layer, connect the active layer to earlier Classes and safely return to an earlier layer. Future
Asset management will own rich Property metadata such as synonyms, units and profiles. This
increment must reserve stable reference identities without inventing that management workflow or
making Neo4j canonical.

## Decision

### Canonical normalized draft shape

PostgreSQL remains the canonical authoring store. `knowledge.tbox_draft_elements` is retained as a
stable identity, block ownership, name, definition, alias, layout and ordinal registry. Exactly one
normalized subtype row exists for each registry row:

- `knowledge.tbox_classes`: stable Class identity, optional single parent Class and optional opaque
  metadata reference ID/URN;
- `knowledge.tbox_properties`: stable Property identity, exactly one owner Class, datatype,
  nullability, unit, vector-index flag and optional opaque metadata reference ID/URN;
- `knowledge.tbox_relationships`: stable Relationship identity, exact source and target Classes,
  fixed typed relationship kind and optional opaque metadata reference ID/URN.

All subtype foreign keys include Workspace and Draft identity, use `RESTRICT`, and Class hierarchy
and endpoint references are deferrable only to permit one validated aggregate replacement in a
transaction. The domain validator still rejects missing/non-Class parents, self-parenting,
duplicate identity/name and every hierarchy cycle before persistence. Forced Workspace RLS and
restrictive Draft actor policies apply to every subtype. The browser receives no SQL, executable
Cypher or provider query path.

`parent_stable_class_id` is the one canonical hierarchy representation. `SUBCLASS_OF` is a derived
safe-editor and canvas edge; it is not duplicated as a Relationship row. Relationship rows are
non-taxonomic Class-to-Class schema relationships.

The metadata reference fields are nullable, opaque mapping slots only. Graph Builder neither
collects nor manages synonyms, units or profiling details in this increment. A later Asset
management ADR must define the referenced aggregate, authorization, lifecycle and resolver before
those fields become an authoring surface. A reference never becomes a provider URL, credential or
query.

### Forward-only layer dependency rules

Every element is owned by exactly one ordered block. A block may reference its own elements or
elements owned by an earlier block. It may not reference an element owned by a later block.
Therefore:

- the active block can freely mutate its own unreferenced elements;
- every other block is rendered as one read-only visual group;
- a Relationship or Class parent created in the active block may target an earlier Class;
- an earlier element referenced by any later block is locked against rename, re-parent, move or
  deletion while that dependency exists;
- only the highest-ordinal (newest) block can be deleted, and deletion is ETag-fenced,
  idempotent and rejected when retained Proposal evidence targets the block.

These rules are enforced in both the browser reducer and the application service. The API does not
trust the client-provided lock badge. The read model derives `locked_by_later_block` from canonical
references and block ordinals.

### Graph Builder interaction model

The active block uses three synchronized regions:

- a left Class Hierarchy tree with stable-key Class creation and drag/drop re-parenting;
- a right React Flow Class canvas with smaller nodes and read-only layer group hulls;
- a bottom safe schema-Cypher editor.

Selecting a Class opens a node-adjacent floating editor. The node expands to show assigned
Properties and accepts an inline Property name for a typed Property addition. Rich Property
metadata remains outside this screen. Invalid safe-editor text stays a local buffer with line and
column diagnostics; the last valid tree/canvas state remains intact.

Block headers are compact and their names are editable. Non-latest delete controls are disabled,
and the server independently enforces the same rule.

## Consequences

- Class hierarchy, Property ownership and Relationship endpoints have explicit PostgreSQL
  integrity instead of a nullable union row.
- Safe `SUBCLASS_OF` round trips do not create two competing hierarchy truths.
- Accumulated layer editing cannot silently mutate or delete a dependency used by later work.
- Existing 0063 rows are deterministically backfilled into subtype tables before the legacy shape
  columns are removed.
- Neo4j remains a disposable release projection and is not involved in Draft hierarchy writes.
- Rich Property metadata management remains deliberately open and requires a separate accepted
  decision.

## Verification

- SQLAlchemy metadata, additive 0064 migration, deterministic canonical 0001 and data-model
  documentation agree on all four draft tables, composite foreign keys, RLS and grants.
- Domain tests cover accepted hierarchy, missing parent, self-parent and cycle rejection.
- Service tests cover later-layer lock rejection and current-to-earlier references.
- UI tests cover tree creation, drag/drop `SUBCLASS_OF` synchronization, invalid-buffer retention,
  floating Property editing, read-only groups and latest-only block deletion controls.
- Strict type checks, lint, backend tests, frontend tests/build and an authenticated browser pass
  remain the release evidence.
