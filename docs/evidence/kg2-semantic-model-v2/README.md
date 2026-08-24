# Metadata Master & Default Lineage Graph Semantic Model V2 evidence

This bundle closes KG2 on Product `e8040e6fedb3b675c5b26854292d08e2010e2ba8`,
progressing from Product `ab6fd454cdbf109c6b82d393a7100e3e38c71f84` and Evidence
`3f09dfd8f78c79ad0588cc6cb93a307f39eed5f5`. The deployed `39083` OCI used the
exact Product tag, was healthy with zero restarts, and returned HTTP 200 for `/` and
`/healthz`. The persistent `39090` status service returned HTTP 200. PREP and OPS were
not executed.

## Discovery and target model

The runtime DataHub reports `v1.6.0` at commit
`059a36c0b035a6057de00114ccac0ea9003d6bc2`. The projection reads canonical DataHub
metadata through the existing adapter: dataset properties, schema fields, tags, glossary
terms and groups, domains, structured/custom properties, and
`upstreamLineage`/`fineGrainedLineages`. DataHub UI scraping and direct reads of DataHub's
backing database are not used.

The prior Metadata Master projection had 12,281 nodes and 24,556 edges. Its principal
gaps were weak typed governance relations and insufficient explicit/inferred provenance.
The V2 model uses deterministic DataHub URNs, typed hub relations rather than asset
pairwise cliques, searchable normalized aliases as properties, and relation provenance.
Description text stays a property/vector document; it is not exploded into word nodes.
No explicit unit metadata was present in this snapshot, so the projection truthfully
reports zero explicit units and zero inferred candidates rather than fabricating values.

## Shared-snapshot refresh and graph quality

One uninterrupted single shared-snapshot refresh captured source snapshot
`197f7d7e4edd00f75e1704738703bd98ef02aaafdbf661398c6779824dd0da2b` and semantic
generation `7faa17ccde7ad2f6f90b84d745b4f449a532be6566d709e5369f4e31412c8f17`.
It built both staging projections, verified complete read-back hashes, and atomically
promoted both active pointers while retaining the previous last-known-good state until
promotion. The exact Product follow-up returned `NO_OP` for both graphs and refreshed
zero embeddings.

- Metadata Master: 12,336 nodes, 45,775 edges, 45,775 explicit and 0 inferred,
  duplicate nodes/edges 0/0, pairwise cliques 0.
- Default Lineage: 1,001 nodes, 1,950 explicit table-lineage edges, duplicate
  nodes/edges 0/0. Column-lineage count is 0 because the current source snapshot did not
  provide usable column edges.
- Refresh cleanup: PREPARING runs 0, active Neo4j namespaces 2, orphan staging
  namespaces 0.

The complete type counts, reconciliation metrics and active projections are in
[`runtime-state.json`](./runtime-state.json).

## Cross-process semantic generation safety

Cross-process semantic generation ownership is enforced for the exact
`(binding_hash, source_generation)` pair by a PostgreSQL session advisory lock. A waiter
rechecks the durable active generation after acquiring the lock and reuses it instead of
calling the embedding provider. A 15-second ownership heartbeat aborts pending provider
batches if the database session is lost. Embedding rows and the active pointer are
published in one transaction.

The focused two-process runtime held producer A's lock for more than one heartbeat.
Producer B waited 10.802 seconds, acquired the lock 3 ms after A released it, and both
returned `REUSE_ACTIVE_GENERATION`; duplicate provider materializations were 0. The
ownership-loss abort test also passed. See
[`cross-process-semantic-generation.json`](./cross-process-semantic-generation.json).

Required gate fields:

- Cross-process semantic generation ownership: exact binding/generation single owner.
- Duplicate materialization prevention: PostgreSQL advisory lock plus durable active
  generation recheck and transactional promotion.
- Same binding concurrent request behavior: wait, then reuse the current generation.
- Protection mechanism: session lock, 15-second heartbeat, AbortSignal ownership loss,
  atomic rows/pointer commit.
- Runtime/focused verification: two processes PASS; ownership-loss focused test PASS;
  duplicate materialization 0.
- Result: PASS.

## Router, MCP, authorization and browser

The final production-path regression is recorded in
[`router-60.json`](./router-60.json): GENERAL 20/20, VECTOR 20/20, GRAPH 20/20,
precision/recall 1.0 and a diagonal 20/20/20 confusion matrix. Its p50/p95 were
24.316/63.242 seconds on the local Ollama DEV host. The final boundary suite in
[`router-boundary.json`](./router-boundary.json) passed 8/8. Both evaluators require
grounding, provenance, and actual traversal where applicable.

Native/MCP comparison in [`mcp-benchmark.json`](./mcp-benchmark.json) measured
806/838 ms and 808/826 ms p50/p95 respectively, with 0% errors and identical structured
results. MCP authorization exposed exactly two granted Tables and their one allowed
lineage edge; ungranted neighbors and shared-semantic-node paths did not leak. The
architecture remains Internal Chat to native adapter and external agents to MCP adapter,
both over the same Core Knowledge Service.

Authenticated browser verification covered Metadata Master search, selection,
directional two-level bounded expansion and type filtering; Default Lineage rendered 15
of 1,001 authorized nodes and 23 of 1,950 edges. Hard reload persisted both managed
Assets and DAILY/NO_OP state. Representative Chat GENERAL (retrieval skipped), VECTOR
(canonical Default Lineage Asset evidence), and GRAPH (actual nodes, relations and
Default Lineage selection) passed. Search, Change Management, Monitoring, Profile and
Knowledge Studio entry also passed; the Studio authoring renderer was not migrated or
modified.

## Source and cleanup

Final source gates: server 122/122, UI 90 files/651 tests, lint, typecheck, build,
static verification and diff-check all PASS. Static verification scans production graph
builder/router files for domain vocabulary and forbidden synonym/graph keyword/question
route maps. `DOMAIN_SPECIFIC_PRODUCTION_HARDCODING = NONE`.

The temporary eval credential was disabled at version 11, three sessions were revoked,
and a direct read-back reported zero active eval sessions. The temporary secret directory
was moved to the system Trash (recoverable), the
candidate container was removed, browser tabs are 0, and inactive embedding bindings
were pruned only after the final generation was active. The retained active binding has
2,002 rows. Canonical DataHub data and both active managed graph namespaces were
preserved.
