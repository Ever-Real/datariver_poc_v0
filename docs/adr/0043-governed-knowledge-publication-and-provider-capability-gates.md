# ADR-0043: Governed Knowledge publication and provider capability gates

- Status: Accepted
- Date: 2026-07-24
- Owners: Product, Data Governance, Security, Data Architecture

## Context

Knowledge Graph Studio already had graphs, changesets, immutable releases, a PostgreSQL adjacency
projection, a Neo4j shadow and development LLM adapters. The previous publication path could,
however, prepare a release and mark the changeset in separate calls. A direct release endpoint also
made it possible for a caller to create a release without proving independent changeset review.
Those paths made a crash, retry or legacy row capable of producing ambiguous publication evidence.

The platform must also run in several deployment shapes. A Mac source-host may use native Ollama
and a local Neo4j container, while the WSL preparation host may use private external Chat,
Embedding and Reranking services and an external Neo4j. Treating all four capabilities as one
boolean made an unavailable optional adapter disable unrelated work and obscured which live
contract had actually passed.

## Decision

### PostgreSQL is canonical

PostgreSQL owns graphs, independently reviewed changesets, immutable releases, release content,
publication lineage and deployment receipts. Neo4j is an optional, rebuildable shadow. A Neo4j
write, read-back failure or outage cannot create, modify or invalidate canonical release content.

### Publication is one atomic command

An approved changeset is published through one store command and one database transaction. The
command locks the graph and changeset, rechecks maker/checker evidence and the graph
classification ceiling, builds the immutable release, reads it back from PostgreSQL, verifies the
exact content hash/count/classification, records a canonical deployment receipt, marks the
changeset published, appends an outbox event and completes idempotency.

Any failure before commit leaves none of those effects. Publication does not activate the graph.
Activation is a separate command and requires a release belonging to the graph plus exactly one
valid, independently reviewed, published changeset lineage and an exact verified deployment
receipt. A canonical PostgreSQL receipt uses `postgres-adjacency-v1`; an accepted Neo4j shadow
receipt uses `neo4j-bolt-shadow-v1`.

The former direct complete-snapshot publication HTTP endpoint is an executable `410 Gone`
compatibility boundary. Legacy releases without the governed lineage are not listed, returned,
activated, exported, projected, exposed as general Chat evidence or consumed by GraphRAG or
release-pinned Sharing. Idempotent replay and every later release consumer revalidate current
lineage; an earlier valid result does not launder evidence after lineage corruption. Graph and
changeset replay is bound to the authenticated actor, while Sharing product/version/grant replay
is bound to the exact owner and resource.

Neo4j query results are identifiers from an optional shadow, not trusted prompt content. Before
composition the application resolves selected node/edge identifiers against the exact PostgreSQL
release and reconstructs properties, classification, provenance and endpoints from canonical rows.
Missing, drifted or over-clearance identifiers fail closed. A Neo4j receipt is valid only for the
fixed shadow adapter/target and exact release hash/count/read-back verification hash.

The optional deterministic semiconductor seed follows the same invariant: separate maker/checker,
an authorized publisher, the exact immutable changeset-operation ledger, canonical PostgreSQL row
reconstruction hash and exact deployment receipt precede setting the active release. A seed is not
an exception to publication governance.

### Classification is a release envelope

The graph classification is the maximum permitted classification for every node, edge and source.
The server enforces the envelope when operations are appended, the full changeset is submitted or
reviewed, a release is published, a PDF source is prepared or analyzed, model output is persisted
and a release is read for projection or inference.

Source classification is immutable and model-generated operations must inherit it exactly.
Authorization and source integrity checks precede classification errors so the endpoint does not
become an object-existence or classification oracle. Legacy over-envelope proposals fail closed;
an independent reviewer may reject them, but the response omits the offending operation content.

`CONFIDENTIAL` and `RESTRICTED` graphs are not eligible for the development inference path.
GraphRAG and Neo4j projection recheck the graph/release envelope before external access.

### Capabilities are independent

Knowledge authoring, source extraction, projection and GraphRAG have separate prerequisites.
Source-host development may enable an exact `127.0.0.1` Ollama origin only when the explicit
development source-host flag is set. Container mode keeps the existing
`host.docker.internal:11434` boundary. Neo4j can be selected independently from local inference;
the legacy aggregate pipeline flag is derived compatibility state, not the authority.

Chat and Embedding use the guarded development OpenAI-compatible contract. Reranking is a separate
private contract because OpenAI does not define a standard rerank endpoint. Its System Settings
profile is fixed to:

```yaml
connection_mode: INTRANET_RERANK_V1
base_url: https://private-reranker.example/v1
model: operator-selected-model
secret_references:
  api_key: file:/run/secrets/intranet_llm_reranker_api_key
options:
  api_style: rerank_v1
  timeout_seconds: 60
  top_n: 10
```

TEST sends one server-authored bounded `POST /v1/rerank` request, follows no redirect, rejects
unsafe or non-allowlisted destinations, caps the decoded response and accepts only unique in-range
indices with finite descending scores in `[0, 1]`. It records `RERANKING_INFERENCE` evidence.
Reranking has no runtime consumer or ACTIVATE path in this phase. A successful connection test must
not be described as Chat readiness or production inference.

The host allowlist is checked before DNS and the returned address set is validated. The current
default HTTP transport can still perform another hostname lookup at connection time. Consequently,
DNS-rebinding closure requires a future transport that pins the vetted address while preserving the
original hostname for TLS verification; this phase does not claim that external gate.

### Evidence and promotion

Local current-source capability evidence and WSL/external-provider evidence are different gates.
The development Mac can close local Neo4j, Chat and Embedding preflight independently. A local
Ollama model that does not implement the fixed rerank contract remains unavailable. WSL/private
DNS, TLS, credentials, model identity, response contract and restart evidence remain an
`EXTERNAL_GATE`.

## Consequences

- Publication retries are atomic and idempotent, while activation remains an explicit governed
  decision.
- Old ungoverned releases are deliberately invisible. Recovery requires accountable migration or
  republishing through a reviewed changeset; no read-path exception is allowed.
- Neo4j can be rebuilt from PostgreSQL and may be omitted where graph traversal is not enabled.
- Operators configure only the capabilities they deploy; unavailable reranking does not block
  Knowledge authoring or a Chat/Embedding path that does not consume it.
- The fixed reranker probe adds Alembic revision `0053`; downgrade is refused while
  `RERANKING_INFERENCE` evidence exists.
- Durable extraction jobs, projection worker recovery, general Chat routing and target-provider
  acceptance remain later phase work.
