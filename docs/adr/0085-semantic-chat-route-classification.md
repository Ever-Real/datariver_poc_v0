# ADR-0085: Semantic Chat route classification under the governed composition binding

- Status: Accepted
- Date: 2026-07-31
- Owners: Knowledge Platform, Application, Security Architecture
- Refines: ADR-0069, ADR-0080, ADR-0082

## Context

The Chat `AUTO` route previously inferred Graph and catalog/vector intent from a small list of
substring matches. That approach misclassified paraphrases and multilingual questions, made the
route label appear more semantic than it was, and encouraged ever-growing keyword lists.

The application must distinguish three bounded intents without accepting an executable query:

1. **GENERAL** — a broadly established explanation that does not request discovery of an internal
   asset;
2. **VECTOR** — discovery or explanation of a table, schema, field, term, policy or other
   catalog metadata asset; and
3. **GRAPH** — a relationship, lineage, upstream/downstream, impact, dependency-path or graph
   selection question.

Graph retrieval is not introduced by this decision. The approved graph adapter remains separate
and can be unavailable while the route is still accurately selected.

## Decision

For `AUTO` only, Chat asks the already configured Chat composition model for exactly one fixed
tool result with a closed enum of `GENERAL`, `VECTOR` or `GRAPH`. The classifier receives only the
bounded user question and a fixed intent contract. It never receives evidence, dataset or graph
identifiers, URLs, Cypher, permissions, classifications or provider credentials. Question text is
treated as untrusted data, not as instructions.

The classifier uses deterministic generation settings, a short output bound and strict parser.
Malformed output, transport failure, timeout and policy-binding failure yield an unavailable route;
they do not silently become a GENERAL or VECTOR search. An explicit user route always bypasses
classification.

The route call is an external inference operation. It is allowed only after authorization,
composition-profile binding validation and conservative request/token budget reservation. Its use
is included in the existing composition-stage audit record. No new provider stage or runtime
environment variable is introduced: both local Ollama and intranet OpenAI-compatible deployments
reuse their approved composition-model configuration.

The service performs authorization, classification access filtering, retrieval, reranking and
final citation reauthorization after routing as before. A `GRAPH` result invokes no graph query
unless the separately governed graph adapter is present; otherwise it reports
`GRAPH_ADAPTER_UNAVAILABLE` rather than degrading to another retrieval method.

## Consequences

- Paraphrased Korean and English questions are routed by meaning rather than an extensible keyword
  allowlist.
- A model can select only a retrieval category, never a database, graph, endpoint or query.
- Moving the application to another approved PC requires only its existing environment-specific
  model configuration; no source-host endpoint or keyword changes are required.
- Automatic routing is intentionally unavailable when its model contract cannot be proved. Users
  can still select an explicit route, which preserves the selected route and reports a missing
  adapter honestly.
- Knowledge Graph implementation and release state stay outside this Chat-menu increment.

## Verification

- Unit tests cover Korean and English paraphrases for all three intents, explicit-route bypass,
  prompt-injection text as data, malformed classifier output and unavailable graph adapters.
- Adapter tests assert fixed tool schemas, zero-temperature bounded requests and rejection of
  invalid tool responses for local Ollama and OpenAI-compatible transports.
- Chat service tests prove policy binding and budget reservation occur before a classifier call and
  that the composition audit records the call once.
- Targeted backend gates, static verification, frontend type/build gates and an authenticated local
  browser check validate the deployed Chat route UI.
