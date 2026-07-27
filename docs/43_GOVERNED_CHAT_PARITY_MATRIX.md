# Governed Chat parity matrix

- Status: implementation baseline
- Scope: general catalog Chat, bounded semantic/vector routing, a future asset-graph adapter seam,
  governed history/favorites, safe answer rendering and authorized evidence detail
- Historical anchors: `ba05ccb` (three-pane evidence workspace), `301280e` (retention-aware local
  development Chat adapter), `046fc31` (later Chat/provider fixes)
- Security authorities: ADR-0011, ADR-0018, ADR-0019, ADR-0035, ADR-0043 and ADR-0048

This matrix distinguishes a visual feature from a server contract. A browser control is not marked
complete unless its server operation is owner/workspace scoped, bounded and covered by a negative
test. A model health probe is not evidence that a retrieval route consumes that model.

| Required capability | Historical/current evidence | Gap at start of Phase 5 | Delivery contract |
|---|---|---|---|
| Conversation and Enter-to-send | `ChatPage.tsx`; `/chat/query` | Enter behavior was browser-default and no multiline escape hint existed | Enter submits, Shift+Enter inserts a newline, duplicate submit is disabled |
| Governed session history | `/chat/sessions`, `/chat/sessions/{id}/messages` | reads were written directly in the HTTP route and message history was unbounded | typed history port, owner/workspace predicate, bounded lists and no-store responses |
| Favorites | response exposed `is_favorite=false` | no mutation or persistence existed | owner-scoped optimistic server mutation persisted on `assistant.chat_sessions` |
| Copy question/answer | none | absent | clipboard operation per message with explicit success/failure status |
| Markdown and tables | plain `<p>` | Markdown was displayed literally | React-only bounded renderer; no raw HTML, executable link, component or script path |
| General routing | `ChatService` catalog search | UI label `AUTO` did not represent a server decision | typed request/decision contract with an audited reason code |
| Vector routing | Knowledge ingestion stores embeddings | no general Chat vector consumer | development adapter over at most 20 provider-authorized catalog candidates, each truncated to 512 characters, and the selected embedding binding |
| Graph routing | release-scoped Knowledge GraphRAG exists separately | general Chat mixed lexical knowledge nodes and could imply graph readiness | typed `GRAPH` route remains adapter-unavailable until the next governed asset-graph task |
| Reranking | fixed `/v1/rerank` probe | no Chat runtime consumer | optional typed reranker orders only the already-authorized evidence bundle |
| Ranked evidence cards | evidence list | cards did not identify rank or open detail | server rank/method plus catalog-only authorized detail and on-demand lineage |
| Workflow state | loading text | provider progress could only be guessed in the browser | server-returned authorization/routing/retrieval/composition/citation/persistence terminal states |
| Provider-policy binding | immutable inference profiles and classification rules | environment-selected adapters were not tied to the rule that approved egress | separate Composition/Embedding/Reranker profile UUIDs plus exact route/provider/model/deployment identity matching, classification-pruned evidence, stage-profile audit and explicit refusal on missing/revoked/mismatched binding |
| Final authorization | pre-retrieval ABAC and citation hash checks | membership, policy or canonical evidence could change while a provider was composing | re-read current membership and canonical catalog/active-release evidence, re-resolve the exact policy ID/hash/version/generation and re-run resource ABAC before citation persistence |
| Rate and token budget | durable assistant-inference budget contracts | interactive Chat had no atomic request/token reservation before retrieval or model calls | workspace/user/full-policy-identity scoped reservation on no-eviction/AOF delivery Redis, additive conservative envelopes for vector input, reranker input, composer input and bounded output, fixed one-minute window, fail-closed dependency behavior and HTTP 429 with retry evidence |
| Owner database boundary | workspace RLS and HTTP owner predicates | child Chat tables did not independently constrain the application role to the owning subject | canonical owner preflight before authorization/provider use, restrictive `FOR ALL TO datariver_app` owner RLS on sessions/messages/runs/citations and migration-time policy-expression fingerprint checks |
| Fail-closed behavior | authorization, classification, retention and citation checks | history ownership, route availability and browser rendering negatives were incomplete | explicit denied-owner, unavailable-adapter, forged-citation, provider-failure and unsafe-Markdown tests |

## Non-goals and honest degraded states

- This phase does not create, publish or infer an asset knowledge graph. `GRAPH` is a typed adapter
  seam and returns an explicit unavailable state until the next asset-graph task supplies a
  governed implementation.
- The browser never supplies an endpoint, model, SQL, Cypher, arbitrary HTTP instruction or tool
  schema.
- Vector candidate enumeration is bounded and authorization-pruned before embedding. It is a local
  development capability, not a claim of a production vector index or target-volume recall.
- Run audit metrics record the external stages actually attempted (`embedding`, `reranker`,
  `composition`) together with each stage's immutable provider profile and the policy identity; a
  configured but uninvoked adapter is not reported as used.
- A connection probe, a routed request and an answer with validated citations are three different
  states and are presented separately.
- Model inventory and connection probes do not authorize evidence egress. Governed Chat additionally
  requires every invoked stage's deployment UUID and exact runtime identity to match the active
  classification rule's immutable provider profile.
- Provider exceptions do not silently switch the selected retrieval strategy.

## Acceptance evidence

Phase 5 closes only when the backend unit/contract tests, strict type checks, frontend tests,
production build and read-only Data Architect/Alpha User/Project Manager reviews pass. Target
browser, WSL and production provider/load evidence remains deployment acceptance and must not be
inferred from local source tests.
