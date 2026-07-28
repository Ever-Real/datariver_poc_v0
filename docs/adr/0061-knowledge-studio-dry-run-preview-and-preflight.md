# ADR-0061: Knowledge Studio dry-run preview and ingestion pre-flight

- Status: Accepted
- Date: 2026-07-28
- Owners: Product, Data Architecture, Security, Knowledge Platform
- Refines: ADR-0058, ADR-0060

## Context

An A-Box Binding Draft is a whitelist, not proof that physical rows are readable or that the
mapping produces valid graph instances. Before a durable ingestion run exists, an author needs a
small preview of the exact mapped fields and machine-readable evidence for missing required
bindings, stale source contracts and revoked source access.

DataHub is a metadata system and does not provide a coherent physical row-sampling contract in the
current deployment. Treating schema-field samples as rows, querying the DataRiver canonical
database as if it were the selected Dataset, or accepting browser-authored SQL would fabricate
evidence and cross bounded-context boundaries.

## Decision

1. Preview is a read-only dry run. It reads one persisted Binding Draft, revalidates its exact
   Dataset metadata pin and asks a deployment-owned `KnowledgeStudioSampleReader` port for five
   through ten rows using only the local Asset UUID, exact source/projection versions and persisted
   field allowlist. The browser cannot submit a query, table name, provider identifier, endpoint or
   credential.
2. A sample adapter must use a server-registered, least-privilege physical-source connection and
   return only bounded JSON scalar cells plus an exact version receipt. DataHub metadata alone does
   not satisfy this port. When no approved adapter exists, the API returns explicit
   `SOURCE_ROW_READER_UNAVAILABLE` evidence and no invented sample.
3. The application traverses the typed T-Box elements and Mapping Rules to build a provider-neutral
   JSON graph. Class previews require one `SUBJECT_ID`; persisted `PROPERTY` rules become properties
   under the target Property canonical name. Preview node IDs are opaque hashes of the binding and
   typed source identity. The response contains no Cypher string and performs no Neo4j, release,
   changeset or source write.
4. The first increment previews Class bindings. Relation mapping lacks an approved endpoint/key
   join contract, so relation preview fails closed with typed evidence instead of constructing a
   guessed edge. The JSON graph still has explicit `nodes` and `edges` collections; a Class preview
   legitimately returns an empty edge collection.
5. Pre-flight validates the exact Draft ETag, accepted T-Box and persisted bindings. Every accepted
   Class is required in contract v1. Each requires a current binding, one `SUBJECT_ID`, mappings for
   all owned Properties where `nullable=false`, a non-stale exact T-Box version, current authorized
   metadata detail and a successful physical-source access probe. Relations are not called
   mandatory until an explicit cardinality/required contract exists.
6. Preview and pre-flight return bounded `ERROR|WARNING|INFO` evidence with stable codes and typed
   locations. Invalid results use normal `200` result documents so the UI can render all evidence;
   stale `If-Match` still returns `412`. Provider exceptions and internal coordinates are
   sanitized.
7. A successful pre-flight is advisory evidence for the current Draft version, not ingestion
   authority. A future durable ingestion command must repeat authorization/version/drift checks,
   pin an immutable binding version and create fenced job/attempt/event records. Until that command
   exists, `Run Ingestion` remains disabled.
8. Sample rows are transient response data. They are never written to Studio Drafts, validation
   tables, logs, caches, PostgreSQL graph assertions or Neo4j by this increment.

## Consequences

- The preview engine and UI can be source-tested with a typed fake adapter while production
  correctly reports unavailable until an approved physical row reader is configured.
- A pre-flight cannot pass merely because DataHub metadata remains readable; both catalog access and
  physical row-reader capability are required.
- The service performs one bounded A-Box read, deduplicates physical sources for validation and
  never issues one source query per Property.
- Persisted immutable binding versions and append-only pre-flight receipts remain part of the
  durable ingestion increment. The current response evidence must not be presented as a release or
  audit receipt.

## Verification

- Pure typed-row-to-JSON-graph tests, including missing/null subject IDs, duplicate identities,
  unsupported relation preview and non-scalar/oversized values.
- Pre-flight positive/negative tests for unbound Class, missing required Property, stale T-Box,
  source version/classification/access drift and missing sample-reader capability.
- OpenAPI tests for required `If-Match`, sample limit bounds, no query/Cypher/provider locator fields
  and no-store responses.
- React Flow overlay tests for sample nodes, click-to-inspect properties, unavailable evidence and a
  disabled ingestion command.
