# 2026-08-12 development DataHub profile diagnostic

## Scope

Read-only inspection of the current development-PC DataHub v1.6.0 and the POC catalog projection.
No DataHub aspect, database source or container was modified.

## Observed evidence

- DataHub GMS was reachable at `http://127.0.0.1:8080`; the UI was reachable at
  `http://127.0.0.1:19002`.
- The POC complete DataHub inventory contained 2,000 Dataset URNs: 1,000 PostgreSQL and 1,000
  Oracle-labelled seed entities.
- DataHub MariaDB `metadata_aspect_v2` contained 3,005 `datasetProperties` and 2,003
  `schemaMetadata` aspect rows, but zero `datasetProfile` aspect rows.
- No reviewed row-count, byte-size or created-date compatibility property was present on the
  inspected DatasetProperties aspects.
- No live Oracle source container and no PostgreSQL source matching the seed recipe were running.
  The Oracle half of the checked-in semiconductor seed is explicitly `execution_mode: MOCK`.
- The completed `POC_DATAHUB_CATALOG_ASSET_V2` projection reported 2,000 schema-bearing assets and
  zero assets with row count, byte size or created date. The split was 1,000/0/0/0 for each of the
  Oracle-labelled and PostgreSQL platforms.

## Conclusion

The current development DataHub can prove schema/column metadata but cannot prove Rows, Size or
Created Date. DataRiver correctly displays those values as unavailable. The UI or Chat adapter
cannot recover a metric that GMS does not contain, and DataHub MCP would read the same absence.

To close the gate, an operator must provide the real Oracle/PostgreSQL connection and least-privilege
credentials, run the native version-matched profiling recipes, then prove non-zero coverage through
`GET /poc-api/datahub/profile-coverage`. Created Date additionally requires the approved extension
described in `docs/23_CATALOG_DATAHUB_INGESTION_AND_EXPORT.md`.
