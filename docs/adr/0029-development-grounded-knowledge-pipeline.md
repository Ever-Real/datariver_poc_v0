# ADR-0029: Development grounded Knowledge extraction and verified Neo4j projection

- Status: Accepted
- Date: 2026-07-21
- Refines: ADR-0023, ADR-0028

## Context

ADR-0023 intentionally stopped at an isolated Neo4j sandbox, while ADR-0028 did not yet allow
Embedding or Neo4j profiles to become startup configuration. The Mac development environment now
needs an end-to-end, locally hosted PDF-to-GraphRAG path. PostgreSQL must remain canonical, model
output must remain an untrusted proposal, and an administrator's successful connection test must
not be confused with process activation or a published Knowledge release.

## Decision

The development profile supports a page-aware PDF pipeline over an integrity-verified private
SeaweedFS object. It parses at most 500 pages, records page hashes and embeddings, and asks the
activated OpenAI-compatible Chat model for typed nodes and edges constrained to the graph's active
ontology. Every model-proposed assertion must carry a short excerpt whose normalized text is an
exact substring of its referenced parsed page. To avoid trusting model-authored quotations, the
server divides normalized pages into stable bounded evidence units; the model selects an opaque
`evidence_id`, and the server resolves it to the canonical excerpt/page/hash. An unknown ID fails
the complete analysis before any changeset is published. An edge whose endpoints are not both in
the same typed response is discarded rather than completed or guessed. The excerpt, excerpt hash
and page hash remain visible provenance through
the draft, immutable release, Neo4j projection and GraphRAG evidence package.

Analysis creates a DRAFT changeset. It does not publish or mutate Neo4j. The normal independent
submit/review flow and recent hardware-WebAuthn `kg.publish` authorization remain mandatory. Model
output can never approve, publish, activate, execute Cypher or choose a different endpoint.

An immutable PostgreSQL release may be copied to a release-scoped Neo4j shadow projection through
server-owned parameterized Cypher only. Verification reads the projected nodes, relationships,
properties, classification and provenance back from Neo4j, reconstructs the canonical
`GraphSnapshot`, and compares its content hash to the PostgreSQL release. Only an exact match may
record `SHADOW_VERIFIED`. GraphRAG retrieval includes both node evidence and traversed relationship
evidence; it applies workspace, release, classification, edge-type, hop and node bounds before any
evidence reaches the model. A returned citation must be an exact ID from that authorized package.

The Admin startup-activation consumers now include `LLM_CHAT_MODEL`, `LLM_EMBEDDING` and `NEO4J`.
TEST performs a fixed strict-JSON Chat completion, one real embedding and an authenticated Neo4j
`RETURN 1` respectively. Their scopes are `MODEL_INFERENCE`, `EMBEDDING_INFERENCE` and
`AUTHENTICATED_QUERY`. ACTIVATE still only selects one AVAILABLE immutable revision and still
requires recent hardware WebAuthn. API and applicable workers read the exact activated versions and
configuration hashes only at startup. Inference audit records preserve whether the binding came
from System Configuration or deployment settings, plus its version and non-secret hash.

The Ollama 0.32.1 OpenAI-compatible grammar compiler does not accept root string
`minLength`/`maxLength` in the GraphRAG response schema. Those two grammar keywords are omitted for
that response only; the same non-empty/20,000-character bounds are enforced immediately after JSON
parsing, before citation validation or audit persistence. Array bounds and strict object shape stay
in the provider schema.

The current 105-page developer exercise remains a synchronous, bounded API operation. Only the
`compose.host-dev.yaml` web proxy extends its read timeout to 900 seconds; the normal image default
remains 30 seconds. This is not a production execution design. Promotion requires a durable leased
inference job/worker, retry classification, cancellation, quotas and target-environment load and
recovery evidence.

## Consequences

- A typed schema alone is no longer accepted as grounding evidence; source substring and hashes are
  part of the release and reviewer-visible contract.
- Neo4j counts or a copied release-hash property alone cannot establish projection integrity.
- Relationship questions receive relationship evidence rather than only neighboring node names.
- A model timeout, invalid JSON, unsupported citation, evidence mismatch or Neo4j content mismatch
  fails closed and never creates a verified release/projection claim.
- DataHub lineage is unchanged. The separate Neo4j instance remains a rebuildable DataRiver
  Knowledge read projection, not DataHub's lineage store and not canonical business state.
- This ADR authorizes the local developer path only; it does not waive the production gates in
  ADR-0011 or ADR-0019.
