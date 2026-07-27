# ADR-0058: Knowledge Studio foundation and managed graph policy

- Status: Accepted
- Date: 2026-07-28
- Owners: Product, Data Architecture, Security, Knowledge Platform
- Refines: ADR-0043, ADR-0044

## Context

Knowledge Studio needs a recoverable authoring aggregate before a governed graph, ontology version,
mapping specification or release exists. The existing `knowledge.graphs` and immutable
`ontology_versions` cannot safely double as partially valid editor state. T-Box composition also
needs one deterministic merge rule, while LLM/file/catalog inputs must remain proposals rather than
direct mutations.

Two platform-owned default graphs require daily A-Box synchronization. That automation must not
silently weaken ADR-0043's review, provenance and atomic-publication invariants.

## Decision

1. `knowledge.studio_drafts` is a separate author-scoped aggregate. Its lifecycle is
   `DRAFT -> REVIEW -> PUBLISHED`; `DISCARDED` is an explicit terminal author action. Drafts
   auto-save with optimistic versions and do not expire or disappear implicitly.
2. Step 1 requires `endpoint_alias`. It starts with a lowercase ASCII letter, contains only
   lowercase ASCII letters, digits and `_`, and is 3–100 characters. On CREATE materialization it
   becomes the graph API identity stored by `knowledge.graphs.slug`. Published aliases are immutable.
3. A Studio CREATE intent materializes `CURATED_KNOWLEDGE`; managed catalog graphs use
   `CATALOG_MIRROR`. `graph_type` is not a business-domain substitute. Domain identity is an exact
   active DOMAIN vocabulary UUID plus its source version.
4. T-Box blocks use integer weights from 0 through 100. Canonical elements are folded in ascending
   `(weight, ordinal)` order, so higher weight overrides lower property/rule keys and equal-weight
   blocks use latest-added (largest ordinal) precedence. Typed tombstones delete keys. Element kind,
   endpoint constraints, classification, provenance, source pins and validation results cannot be
   overridden by this convenience rule.
5. Step 2 file/DB inputs may produce typed schema proposals only. No source row is written to a
   graph database. Step 3 binds actual rows to an approved T-Box through versioned mapping contracts
   and durable ingestion jobs.
6. Cypher editor text is parsed by a lexer and grammar into an AST. AST visitors produce typed
   operations and React Flow projections; the reverse path also traverses typed structures.
   Regex-based Cypher parsing and raw Cypher execution/pass-through are forbidden. Invalid text
   retains the last valid accepted graph.
7. The metadata-lineage and glossary default T-Boxes are editable only by System Admin. Daily
   A-Box auto-publication is allowed only when a separately approved immutable managed policy pins
   the exact graph, PUBLISHED T-Box checksum, source and mapping contract versions, service
   principal, schedule and classification ceiling. Each run revalidates those pins and records an
   atomic publication/no-op/failure receipt. Drift, missing input, authorization revocation or
   partial failure cannot change the active release.

## Architecture consequences

- Studio persistence, commands and authorization live in the Knowledge bounded context. Browser
  state, Airflow state, LLM output, uploaded text and graph projections are not canonical truth.
- Studio APIs require idempotency and version fencing. RLS limits CREATE drafts to their author;
  review/materialization adds explicit reviewer/system policies rather than broadening the author
  policy.
- Graph and ontology provenance columns are additive and nullable for legacy rows. New Studio
  materialization must provide domain, creator/editor and base-contract provenance; it may not
  invent a backfill.
- The managed-graph policy is a standing, reviewable automation authorization, not an implicit
  exception. Phase 6 remains gated on Security/Operations acceptance, target scheduler recovery,
  source read-back and projection rebuild evidence.

## Rejected alternatives

- Persisting incomplete editor state in `graphs` or `ontology_versions`: exposes drafts to Registry,
  Chat, GraphRAG and release paths.
- Expiring or silently deleting autosaves: conflicts with the approved author recovery policy.
- Letting LLM/parser output mutate the accepted graph immediately: removes the proposal approval
  boundary.
- Regex-based Cypher rewriting: cannot provide grammar-aware safety, stable identity or reliable
  round trips.
- Letting scheduler success imply publication: makes a fallible external orchestrator canonical and
  bypasses provenance/review controls.

## Verification

- Migration/model/data-model parity, FORCE RLS, least-privilege grants and no-delete behavior.
- Idempotent create/autosave/discard, stale version and cross-workspace/cross-author negative tests.
- Lexer/parser/AST/typed-operation/React Flow round-trip tests including unsupported syntax.
- Managed-policy pin, drift, empty/no-op, replay, concurrent-run, revocation and partial-failure
  tests before Phase 6 activation.
