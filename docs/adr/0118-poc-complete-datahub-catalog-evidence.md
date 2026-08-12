# ADR-0118: POC complete DataHub Catalog evidence and MCP boundary

- Status: Accepted for the authentication-free POC only
- Date: 2026-08-12
- Refines: ADR-0116, ADR-0117
- Does not modify: DataHub canonical ownership, production authorization, provider mutation, or
  production vector chunking

## Context

The table-level pgvector reconciliation contained every DataHub Dataset URN, but its V1 document
contained only table identity, description, ownership, domain, tags and terms. Column identity,
native type, column description/tag/term and table profile observations were fetched only after a
small candidate set had already been selected. The projection therefore had complete URN coverage
but incomplete semantic recall: a question containing only a column term could fail to select the
correct table.

DataHub also provides an MCP server. MCP is valuable when an external agent needs a standard tool
surface, but it reads the same GMS metadata and cannot repair missing DatasetProfile or
DatasetProperties aspects. Replacing the fixed in-application adapter with an LLM-mediated MCP tool
loop would add another service and decision boundary without improving source completeness.

## Decision

The POC continues to read DataHub through server-owned, typed GMS GraphQL operations. The complete
inventory reconciliation now maps, for every returned Dataset:

- physical and qualified name, platform, database, schema and table/view kind;
- domain, all provider owners, editable/source description, tags and glossary terms;
- every provider-returned schema field with native/logical type, editable/source description,
  tags and glossary terms;
- the newest usable non-sample full-table row/column/size observation and the approved created-date
  contract from ADR-0117.

The resulting document is stored in the table-level pgvector projection under binding contract
`POC_DATAHUB_CATALOG_ASSET_V2`. The binding change makes V1 rows ineligible. Reconciliation starts
in the background when the POC server starts and is also scheduled after semantic queries. Exact
asset questions re-read the complete typed entity before composition. No column slice or text
truncation is applied to the selected evidence record; a provider-absent value stays absent.

The API exposes `GET /poc-api/datahub/profile-coverage` as a read-only diagnostic. It first counts
the completed V2 DataHub projection persisted in pgvector and otherwise falls back to the live
provider inventory. Its `source` and `projection_contract` fields make that evidence surface
explicit. It reports, by platform, the number of Dataset assets with schema, row count, byte size
and created date. Counts describe provider observations, not inferred quality.

The Chat composer receives the complete evidence, while the human evidence card intentionally
shows only citation rank, table name, table/view kind and provider description. Presentation
compactness does not reduce the server evidence used for composition.

DataHub MCP remains an optional interoperability surface for separately governed external agents.
It is not required by this POC and must not become a browser credential path, a second source of
truth, or a reason to accept arbitrary tool/GraphQL input. A future MCP adoption requires its own
service authentication, tool allowlist, latency/failure and prompt-injection review.

## Consequences

- Semantic discovery can match table-level and column-level metadata across the complete DataHub
  inventory after reconciliation.
- Reconciliation payload and embedding cost increase with total schema size; production still
  requires a measured chunking/indexing design rather than treating this POC table document as a
  scale claim.
- MCP does not solve missing profile data. The source connector or approved profile publisher must
  first emit the relevant DataHub aspects.
- The diagnostic can prove that a Prep or development DataHub contains profile observations without
  exposing source credentials or fabricating metrics.
