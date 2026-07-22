# Catalog DataHub ingestion, metadata and export operation

This record covers DataHub `v1.6.0` and the DataRiver catalog projection. It is
an implementation and activation guide, not evidence that a remote DataHub or
production database has already been changed.

## What each field requires

| Source | Rows / Size | Created Date | Required action |
|---|---|---|---|
| PostgreSQL | DataHub `DatasetProfile.rowCount` and `sizeInBytes`; produced only when profiling is enabled and the profiling account can read catalog statistics and invoke `pg_table_size`. | PostgreSQL does not retain a table creation timestamp in its regular system catalogs, and the standard DataHub PostgreSQL source does not set `DatasetProperties.created` for a dataset. | Enable bounded table-level profiling; use an approved custom source or DDL/audit registry to emit the canonical DataHub `DatasetProperties.created` timestamp in milliseconds. |
| Oracle | DataHub `DatasetProfile.rowCount` and `sizeInBytes`; candidate selection uses `ALL_TABLES` or `DBA_TABLES` statistics. | The v1.6 source reads `ALL_OBJECTS` / `DBA_OBJECTS.CREATED` for stored procedures, but does not map that value to a table dataset's `DatasetProperties.created`. | Enable bounded table-level profiling, keep Oracle statistics current, and add the same approved source extension that emits canonical `DatasetProperties.created` for tables. |

DataRiver never converts an unavailable observation to `0` or a guessed date. The
detail API reads `DatasetProfile` for Rows/Size and `DatasetProperties.created`
for Created Date. It now also reads both source `properties.description` and
governed `editableProperties.description`, preferring the governed value.

## Recommended profiling recipe

Add this below `source.config` for each PostgreSQL and Oracle ingestion recipe,
then narrow the patterns and limits to an approved initial scope. Do not place a
password or DataHub token in a committed recipe.

```yaml
table_pattern:
  allow:
    - "approved_schema\\..*"

profiling:
  enabled: true
  profile_table_level_only: true
  report_dropped_profiles: true

profile_pattern:
  allow:
    - "approved_database.approved_schema\\..*"
```

For Oracle, the connector's v1.6 default profile-candidate limits are 5 GiB and
5,000,000 rows. Tables above either limit are deliberately skipped. Select a
capacity-approved `profile_table_size_limit` and `profile_table_row_limit`; use
`null` only after a documented load review. Refresh Oracle optimizer statistics
before the ingestion run, because the candidate filter uses those statistics even
when they are stale.

For PostgreSQL, use `profile_table_row_count_estimate_only: true` only when an
estimate is acceptable. The connector separately calls `pg_table_size` over
`information_schema.TABLES`; its log explicitly reports missing permissions and
continues without storage size. Give the dedicated ingestion account only the
catalog/statistics access required by the approved scope, test it against the
actual source, and retain the run report. Do not grant broad administrator access
merely to obtain a profile.

For Oracle, choose the least-privileged `data_dictionary_mode` that covers the
approved schemas (`ALL` or `DBA`) and grant the corresponding DataHub documented
dictionary views. A missing `ALL_TABLES` / `DBA_TABLES` read or stale statistics
can make Rows/Size appear absent even though the dataset itself was ingested.

## Created Date extension contract

No DataRiver UI setting can reconstruct these dates. The accountable DataHub
owner must implement and review one of the following before enabling it:

1. Extend the PostgreSQL and Oracle source to read the organization-approved DDL
   audit/registry (or Oracle object date) and emit `DatasetProperties.created`.
2. Add a controlled post-ingestion transformer that writes the same typed aspect
   with a traceable source/version.

The timestamp must be the actual table-creation instant in epoch milliseconds,
must be idempotent, must not overwrite a more authoritative value, and must be
scoped to the source dataset URN. A custom property alone is not sufficient for
the current DataRiver detail contract; emit the typed `created` field or make a
separate reviewed adapter contract change.

## Description synchronization

DataHub separates source descriptions from manual/governed descriptions. Before
this change, the catalog scan queried only `properties.description`; assets whose
description existed only in `editableProperties.description` consequently lost
their text during DataRiver projection sync. The typed scan and detail queries
now read both and use a non-blank editable description first.

After deployment, run a complete authorized catalog projection sync so existing
rows are replaced by the corrected description. This does not widen the
workspace, classification, source-version, or policy boundary.

## Safe export activation

CSV/XLSX export is intentionally a server-managed, owner-scoped job. It is not a
browser-side table dump. The buttons are disabled when the API reports the
feature unavailable, including the default local setting
`CATALOG_EXPORT_WORKER_ENABLED=false`.

To activate it, an operations owner must first provision the isolated
`datariver_export` database credentials and the required object-storage secret
references, then enable the flag for both API capability reporting and the
worker. The local bootstrap/run command is documented in the project README:

```powershell
./scripts/bootstrap.ps1 -DataHubToken '<scoped-service-token>' `
  -DataHubEmbedOrigin 'http://127.0.0.1:9002' -EnableCatalogExportWorker
docker compose --profile catalog-export -f compose.yaml -f compose.identity.yaml `
  up -d --build catalog-export-worker
```

Verify capability, create, status and download with two permitted identities and
record audit correlation IDs without recording signed download URLs or secrets.
If activation is not approved, leave the flag disabled; DataRiver must not bypass
the isolated worker or export directly from the browser.

## Remote activation checklist

- [ ] DataHub run report shows profiling enabled, selected candidates, and no
  unreviewed permission/profile-limit failures.
- [ ] PostgreSQL and Oracle test datasets expose non-null `rowCount` and
  `sizeInBytes` in their latest full-table `DatasetProfile`.
- [ ] The approved Created Date extension emits a non-null
  `DatasetProperties.created` for one table in each source.
- [ ] A source-only and an `editableProperties`-only description both survive a
  complete DataRiver projection sync; the editable description wins when both
  exist.
- [ ] Export worker capability, job creation, final artifact metadata and
  permission revalidation succeed in the target environment.
