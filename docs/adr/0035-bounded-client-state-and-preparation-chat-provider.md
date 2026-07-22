# ADR-0035: Bounded client state and preparation Chat provider

- Status: Accepted
- Date: 2026-07-22
- Refines: ADR-0011, ADR-0019, ADR-0030, ADR-0034

## Decision

The browser must not retain an unbounded catalog working set. Search results remain server-paged at
at most 100 rows, resource-tree branches retain at most 200 nodes each and at most eight expanded
branches, and asset schema fields are serialized in server pages of at most 200 fields (100 by
default). DataHub detail enrichment retains at most 1,000 unique schema fields and exposes both the
retained count and a bounded `1,001+` source lower bound when truncated; it does not allocate an
unbounded uniqueness set merely to calculate an exact total. Closing or evicting a tree branch
aborts its request and discards its descendants and stale in-flight results.
The DataHub HTTP adapter also streams every provider response through an 8 MiB hard limit before
JSON parsing, so the schema-field cap is not defeated by an oversized upstream body.

The Linux/WSL preparation profile may use the development-only intranet OpenAI-compatible Chat
binding from ADR-0030 for the ordinary grounded `/chat/query` flow even when the Knowledge pipeline
and Neo4j projection are disabled. The API key remains a mounted file secret, the endpoint remains
an exact allowlisted private-network HTTPS `/v1` origin, and the request is one fixed
`submit_grounded_answer` tool contract. Model output is untrusted and the application validates all
cited chunk identifiers against the already-authorized evidence set. The shared transport streams
success bodies through a 2 MiB hard limit before JSON parsing, including when the provider omits or
misstates `Content-Length`.

Database-backed System Settings activation remains disabled in the preparation profile. Deployment
environment values and mounted secrets are the runtime source of truth; the Admin screen may report
those connectors but cannot activate a stored database revision.

Redis cache and delivery must use different service origins, not merely different logical database
numbers on one instance, because their eviction/persistence policies conflict. S3 private/public
endpoints are credential-free HTTP(S) origins without path/query/fragment. Development Neo4j may
use a separate private server only when its exact port-7687 hostname appears in the deployment
allowlist; PostgreSQL releases remain canonical.

## Consequences

- Large catalogs and wide tables remain browsable without accumulating the full dataset in one
  browser session.
- An externally operated private model server can provide ordinary Chat without requiring
  Embedding or Neo4j. GraphRAG still requires Chat, Embedding and Neo4j together.
- Public/SaaS inference and production inference remain outside the accepted boundary and fail
  closed until the production gates in ADR-0011 and ADR-0019 are satisfied.
