# ADR-0116: POC catalog vector projection and static document presentation

- Status: Accepted for the authentication-free POC only
- Date: 2026-08-12
- Refines: ADR-0080, ADR-0082, ADR-0115
- Does not modify: production Governance Document sanitization, Chat authorization or canonical
  Catalog ownership

## Context

The POC Chat route called the Embedding endpoint but retrieved only a few lexical DataHub search
results. PostgreSQL already included pgvector, yet no Catalog projection consumed it. HTML document
imports also retained semantic markup but intentionally discarded every style, making an uploaded
policy visually different from its static source. Executing imported JavaScript or accepting raw
CSS would violate the existing active-content and stored-XSS boundary.

## Decision

The POC server owns a rebuildable `poc_catalog_embedding` projection keyed by the exact DataHub
origin hash, Embedding endpoint/model binding and asset URN. It enumerates the complete bounded
DataHub dataset inventory, forms one bounded asset-level document from provider name, qualified
name, platform, owner, domain, description, tags, terms and created timestamp, and embeds only
changed content in batches. A source-generation hash removes assets no longer present. Semantic
Chat embeds the question, performs exact pgvector cosine ordering over the same binding, then
re-reads each selected asset through the live fixed DataHub detail query before reranking or
composition. Exact-name lookup remains deterministic. Graph questions may use this projection only
for entity resolution; upstream and downstream relationships come from the fixed DataHub lineage
query and retain their provider direction. Neo4j remains optional rebuildable evidence.

The table has no ANN index and stores no credential. `npm run poc` without PostgreSQL uses the same
fixed interface with process-memory vectors for that process lifetime. Neither store is canonical
metadata or production authorization evidence. The single POC identity retains the already
accepted open POC policy; production Workspace, membership, RLS, classification and citation gates
are unchanged.

For POC HTML file import only, the browser may translate a bounded subset of source `<style>` rules
and inline declarations into a normalized `data-governance-style` presentation token. Supported
selectors, rule counts, match counts, properties and lengths are bounded. URL-bearing CSS,
imports, expressions, custom variables, fixed/absolute positioning, overlays and unsupported
properties are discarded. The existing DOM-to-React allowlist validates the token again and maps
it to React style properties. Script/style nodes, event handlers, forms, media, embedded content
and unsafe links remain suppressed; no raw HTML sink, iframe or script execution is introduced.
Production canonical Governance Document versions continue to use the ADR-0080/0082 server
sanitizer contract and may discard this POC-only presentation token.

## Consequences

- The first semantic question after an empty projection may wait for a full inventory embedding
  pass; later runs are hash-incremental. This is not a production latency or recall claim.
- Relevant Chat candidates include every inventory asset at table level, while selected candidates
  receive live bounded column/profile enrichment before composition.
- A DataHub asset without `DatasetProfile` rows/size or typed `DatasetProperties.created` remains
  explicitly unavailable. The POC does not fabricate zeroes or dates.
- Uploaded static document color, spacing, typography, borders and bounded layout can be retained,
  while JavaScript-dependent widgets remain intentionally unavailable.
