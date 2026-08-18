# DEV Knowledge K6 entry audit

## Scope

- Read-only entry audit for the conditional Knowledge K6 Chat slice.
- Current Product and deployed OCI: `fca4535cab544560bd06486dc363e6df0c6df27f`.
- Authoritative runtime: Node POC at `http://127.0.0.1:39083/`.
- K5 remains `HOLD_KNOWLEDGE_ABOX_PERSISTENCE_DECISION`; no Product, database, provider,
  container or Neo4j mutation was performed.

## Existing reusable seams

- `KnowledgeChatPage` already maintains a conversation surface separate from Main Chat, lets the
  user select a graph/release/start node, bounds direction/hops/nodes, and renders cited evidence,
  a graph preview and model audit information.
- Its tests exercise the intended release-scoped request and prove that it does not route through
  general Chat. These are component contract tests with injected responses, not Node runtime E2E.
- The repository's non-authoritative FastAPI implementation contains release-snapshot
  authorization, verified-projection gating, bounded Neo4j retrieval, provider composition and
  citation projection. It is useful source material but cannot be used as runtime proof or started
  as a second API authority.
- The Node Product already has current `knowledge.read/manage/review` capability seams, K1
  graph/release identity and parameterized Neo4j primitives, K2 Asset/version lifecycle and the
  existing Chat provider composition. No new capability or conversation store is required.

## Authoritative Node gap

Current route-registry resolution returned:

```text
GET  /poc-api/knowledge/graphs                                      NO_ROUTE
GET  /poc-api/knowledge/graphs/{graph}/releases                     NO_ROUTE
GET  /poc-api/knowledge/graphs/{graph}/releases/{release}/snapshot  NO_ROUTE
POST /poc-api/knowledge/graphs/{graph}/releases/{release}/graphrag  NO_ROUTE
POST /poc-api/llm/chat                                              chat.query
```

- K1 materializes exact DataHub Table/Column source identities, not a K5 A-Box instance Release.
- K2 Draft/release documents establish lifecycle authority but do not provide the governed
  instance snapshot and verified projection required for graph retrieval.
- Calling general Chat with fixture evidence, exposing the generic `/poc-api/neo4j/graph` route or
  using the legacy FastAPI response would bypass the requested Asset/version authorization and
  would not close K6.

## Minimal K6 path after K5

1. Require an ACTIVE Knowledge Asset and exact pinned version with a verified K5 instance
   projection receipt.
2. Hydrate current `knowledge.read` authority, canonical grade and every bound-Table grant once per
   request; Draft, Archived, inaccessible or stale releases are hidden.
3. Add only bounded Node handlers for Asset/release selection, authorized snapshot and GraphRAG.
   Reuse the existing Chat provider and parameterized Neo4j access; never accept raw Cypher.
4. Restrict graph retrieval before traversal by exact graph/release and authorized entity scope,
   then compose only the returned evidence and emit Asset/version/entity/relation/source citations.
5. Keep Knowledge Chat conversation state separate from Main Chat. K7 routing remains untouched.

## Acceptance after dependency closure

- Browser: select an authorized ACTIVE Asset/version, simple and multi-hop questions, answer,
  compact citation plus expanded provenance, hard reload, desktop/mobile and understandable empty,
  loading and error states.
- Security: unauthorized Asset and bound Table hidden, Draft/Archived releases absent, invalid or
  stale version denied, bounded traversal/totals, no raw Cypher and no general-Chat fallback.
- Runtime: exact Product SHA equals OCI, current provider result, verified K5 projection receipt,
  fresh independent Node validator and disposable cleanup.

## Status

- K6 Product mutation: `NOT_STARTED_DEPENDENCY_GATE`.
- K6 may start only after K5 is `COMPLETE_RUNTIME_VERIFIED` and the worktree is clean with no
  unresolved security blocker.
- New tables 0; dependencies 0; services 0; containers 0; queues 0; workers 0; frameworks 0;
  capabilities 0.
