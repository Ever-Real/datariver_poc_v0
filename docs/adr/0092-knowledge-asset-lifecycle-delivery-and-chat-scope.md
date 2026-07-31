# ADR-0092: Knowledge Asset lifecycle, typed delivery API and governed Chat scope

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Data Architecture, Knowledge Platform, Application, Security Architecture
- Refines: ADR-0043, ADR-0044, ADR-0058, ADR-0069, ADR-0070, ADR-0072, ADR-0083, ADR-0085

## Context

Knowledge Studio already separates author-owned Drafts from independently reviewed immutable
T-Box/A-Box mapping contracts. The product navigation, however, still exposed disconnected
operating models: Registry listed a legacy graph array, Information Management stopped at Domain
and Property profiles, while the actual typed Changeset and governed PDF-to-Changeset pipeline
lived outside the primary Knowledge workflow.

The platform Chat semantic router can select `GRAPH`, but it intentionally cannot choose a graph.
Graph evidence was therefore disabled in the HTTP composition root. Adding graph names or keyword
branches to Chat would duplicate policy, bypass Release state and create an unreviewable routing
classifier.

Published graphs already have an immutable endpoint alias (`knowledge.graphs.slug`) and safe
Release endpoints, but there was no owner-managed opt-in stating that an alias is an external
service surface or that a graph may be selected by Chat. A raw Cypher endpoint, browser-supplied
query, anonymous alias or provider credential is not acceptable.

## Decision

### One user journey with four canonical stages

The Knowledge workspace presents these responsibilities without a second source of truth:

1. **조회 및 생성** — server-paged Asset discovery, create/edit/archive and focused immutable
   Release history;
2. **Studio** — Step 1 contract, sequential T-Box blocks and A-Box Mapping contract authoring;
3. **정보 관리 / 인스턴스·적재** — direct typed A-Box Changesets, governed PDF+LLM
   Proposal-to-Changeset, published DB Binding inspection, independent review and instance Release;
4. **정보 관리 / API & Chat routing** — external API opt-in and graph selection policy.

PostgreSQL remains canonical. T-Box structure, Studio Release, A-Box Changeset/Release and Neo4j
Projection remain separate state machines. “Mapped”, “Published schema”, “Published instances”
and “Verified projection” are never represented by one status.

The existing PDF worker is reused after a graph has an approved T-Box. It produces a typed DRAFT
Changeset with provenance; model output never publishes instances. Catalog/DB selection remains an
immutable source-version and field-allowlist Mapping contract. A physical source sample is not
represented as a full ingestion run. An approved batch reader/worker is still required before a
DB Mapping can claim full source materialization.

### Additive Registry read model

`GET /knowledge/registry/assets` is an additive bounded read API. It does not change the legacy
`GET /knowledge/graphs` contract. It joins the active Studio Release, active instance Release,
normalized T-Box counts, Binding counts, identity display fields, latest Projection state and
Delivery Policy in one bounded query. It applies classification and domain pruning in SQL, uses
allowlisted sort modes and an opaque keyset cursor, and returns no provider credential,
object-store coordinate or physical connection secret.

The operational detail API returns the active released schema index, immutable Binding summaries
and bounded Projection receipts. Historical instance Releases and snapshots continue to use the
existing release APIs, so selecting a historical version updates graph preview without mutating
the active pointer.

### Delivery Policy aggregate

`knowledge.delivery_policies` is one mutable, versioned policy per graph:

- `api_enabled` opts the graph alias into the typed endpoint resolver;
- `chat_enabled` permits the graph to participate in Chat scope resolution;
- `priority` is an explicit integer from 0 through 1,000;
- `match_any_terms`, `match_all_terms` and `excluded_terms` are normalized NFC/casefolded,
  bounded literal conditions.

Terms are data, not executable expressions. Regex, SQL, Cypher, template evaluation and arbitrary
provider queries are not accepted. An enabled Chat policy requires at least one positive condition.
The same term cannot be required and excluded. Mutations require `kg.edit` on the exact graph
domain/classification resource, an idempotency key and optimistic version fencing. The table uses
forced workspace RLS and column-limited update grants.

The alias resolver is authenticated and ABAC scoped. It returns only relative DataRiver API paths
for the current active Release. It does not make a graph public, mint a token, expose Neo4j/Bolt or
accept raw graph queries.

### Chat scope boundary

The semantic Chat router continues to choose only `GENERAL`, `VECTOR` or `GRAPH`. After `GRAPH`,
Chat calls the read-only `KnowledgeGraphScopeResolver` with Workspace, authorized subject, bounded
question text, optional explicitly requested graph ID and request audit context.

The Knowledge context selects only a non-archived graph with an active instance Release and enabled
Delivery Policy inside the caller's classification/domain envelope. Automatic selection evaluates
literal ANY/ALL/excluded conditions, then ranks by explicit priority and condition specificity. An
equal top rank is ambiguous and returns no scope rather than choosing a graph arbitrarily. Explicit
selection still requires an enabled policy and the same authorization checks.

The returned scope pins graph, active Release, policy ID and policy version. The evidence adapter
queries only that graph and populates `domain_id` from the canonical graph. Chat never contains
graph-name or business-keyword branches and does not repair missing authorization metadata in the
browser.

## Consequences

- Users can distinguish schema publication, instance publication and Projection health from the
  Registry without N+1 release/source queries.
- Direct A-Box input and PDF+LLM extraction share the same typed Changeset review/release path.
- Existing Studio DB Bindings are visible in Information Management and remain version-pinned;
  they do not falsely claim that a full database was ingested.
- Every published graph can remain internal-only; API and Chat participation are explicit,
  separately controlled switches.
- Chat routing is deterministic, owner-managed and auditably tied to a policy version without
  weakening semantic intent classification.

## Verification

- Domain tests cover Unicode normalization, term bounds, conflicting conditions and matching.
- Service tests cover explicit scope, automatic priority/specificity, ambiguity, classification,
  domain and `kg.edit` authorization.
- Persistence tests cover forced RLS, least-privilege grants, unique graph policy, keyset cursor,
  active Release and Delivery Policy joins, and deterministic migration `0080`.
- Chat tests prove GRAPH retrieval is graph-scoped, disabled/unmatched policies return no graph
  evidence, and evidence carries canonical domain scope.
- Frontend tests cover server-paged Registry, focused historical preview, Binding/Projection/API
  drawer states, direct typed Changeset, PDF pipeline reuse, DB Binding visibility and fenced
  Delivery Policy save.
- Full Ruff, strict mypy, pytest/static, TypeScript, ESLint, Vite production build and authenticated
  browser verification are release evidence; source-only passes are not production claims.
