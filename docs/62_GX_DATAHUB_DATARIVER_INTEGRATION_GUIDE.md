# GX, DataHub and DataRiver quality integration guide

This guide separates three responsibilities that must not be conflated:

1. the PostgreSQL/Oracle DataHub source connector publishes schema and DatasetProfile metadata;
2. Great Expectations (GX) evaluates approved rules against the source and publishes validation
   evidence;
3. DataRiver reads DataHub metadata and, in the production architecture, owns the governed Rule,
   Run and result lifecycle.

The current authentication-free POC can display live DataHub assets, fields and profile
observations and can dispatch the fixed Airflow DAG. It does not turn an Airflow success or a raw
GX result into a canonical DataRiver quality result. That final control plane remains the typed
service described by `docs/52_GX_QUALITY_MANAGEMENT_PRD_CHECKLIST.md` and
`docs/54_PHASE8_QUALITY_AUTHORING_AND_EXECUTION_READINESS.md`.

## 1. Recommended topology

```text
Oracle / PostgreSQL
   ├─ DataHub connector ──> DataHub GMS
   │                         ├─ DatasetProperties / SchemaMetadata
   │                         └─ DatasetProfile
   └─ GX worker <── Airflow fixed DAG
          ├─ typed result ──> DataRiver quality API / PostgreSQL (canonical target)
          └─ DataHubValidationAction ──> DataHub Assertions (discovery copy)

DataRiver Web ──> same-origin DataRiver gateway ──> DataHub GMS / quality API
```

GX must run in the isolated worker, not in the browser, POC Web process or Airflow scheduler image.
Database credentials belong to the connector/worker secret store. DataHub and GX remain fallible
providers; neither writes DataRiver canonical business tables directly.

## 2. Publish database profile metadata to DataHub

For PostgreSQL, start from `infra/datahub/recipes/semiconductor_postgres.yml` but replace the seed
schema with the approved real schemas. For Oracle, create a native `type: oracle` recipe from the
DataHub version-matched source documentation; do not reuse
`semiconductor_oracle_mock.yml`, which is explicitly a mock metadata manifest.

The minimum reviewed profiling block is:

```yaml
profiling:
  enabled: true
  profile_table_level_only: true
  report_dropped_profiles: true
```

Narrow `table_pattern` and `profile_pattern`, use a least-privilege ingestion account, and retain
the DataHub ingestion report. PostgreSQL requires catalog/statistics access and permission to call
the size function used by the connector. Oracle candidate selection depends on accessible and
current `ALL_TABLES`/`DBA_TABLES` statistics and connector size/row limits. The detailed caveats and
created-date extension contract are in `docs/23_CATALOG_DATAHUB_INGESTION_AND_EXPORT.md`.

After each run, verify both DataHub and DataRiver:

```bash
curl -fsS http://127.0.0.1:39080/poc-api/datahub/profile-coverage | jq .

curl -fsS --get http://127.0.0.1:39080/poc-api/datahub/asset \
  --data-urlencode 'urn=urn:li:dataset:(...)' | \
  jq '{name,dataset_kind,quality,created_at,schema_fields_total}'
```

`profile-coverage.source` identifies the evidence surface used for the count. A
`DATAHUB_GMS_VECTOR_PROJECTION` response is the completed V2 DataHub projection persisted in
pgvector; `DATAHUB_GMS_LIVE` is a direct provider inventory fallback. Both use DataHub metadata,
and neither invents a missing observation.

Acceptance requires non-zero `row_count_available` and `size_bytes_available` for each intended
platform. `created_at_available` can remain zero until an approved source extension emits the real
table creation timestamp. DataRiver must not substitute the current time or zero.

## 3. Run GX and publish assertion discovery metadata

Pin the repository-approved GX version and connector driver in the isolated quality-worker artifact.
Create Data Sources and Data Assets from a server-owned manifest, compile only the typed rule kinds
allowed by ADR-0077, and run a Checkpoint. Do not accept arbitrary GX class names, kwargs, SQL,
Python, YAML or connection coordinates from the browser.

Install the DataHub GX integration in the worker and configure the version-matched
`DataHubValidationAction` with the internal GMS URL and service token. It publishes DataHub Assertion
entities associated with the same Dataset URNs. The DataHub platform instance and environment must
match those used by the database ingestion recipe; otherwise GX results attach to a different URN
and appear missing.

Use the official version-matched references:

- <https://docs.datahub.com/docs/metadata-ingestion/integration_docs/great-expectations>
- <https://docs.datahub.com/docs/generated/ingestion/sources/postgres>
- <https://docs.datahub.com/docs/generated/ingestion/sources/oracle>

DataHub Assertions are a discovery/read copy. In the target architecture, the GX worker must also
submit the normalized counts, outcome, compiler/GX version and evidence hash through the service-only
DataRiver quality completion command. Raw unexpected values, source rows and secrets are not stored.

## 4. Airflow dispatch

The POC gateway allows only fixed DAG identifiers, including `datariver_quality_dispatch`. Set the
DataRiver Web environment to the Airflow API origin, not the container's internal port:

```dotenv
AIRFLOW_URL=http://airflow-host.internal:8888
AIRFLOW_USERNAME=datariver_poc
AIRFLOW_PASSWORD=<host-local-secret>
```

For Airflow 2.x the POC uses the v1 Basic-auth API; for Airflow 3.x it first requests the v2 auth
token. The DAG must call back to a routable DataRiver address; `127.0.0.1` inside the Airflow
container is the container itself. When this repository's optional Airflow Compose is used:

```dotenv
AIRFLOW_DATARIVER_URL=http://host.docker.internal:39080
```

The POC dispatch demonstrates connectivity only. A production-quality flow is:

```text
human run request -> canonical Run/outbox -> service-only Airflow dispatch
-> fenced GX worker claim -> source execution -> normalized result commit -> DataHub assertion copy
```

## 5. Environment ownership

Only these existing provider values belong in the DataRiver POC `.env`:

```dotenv
DATAHUB_GMS_URL=http://datahub-gms.internal:8080
DATAHUB_GMS_TOKEN=<host-local-secret-or-empty-only-for-auth-disabled-local-gms>
AIRFLOW_URL=http://airflow.internal:8888
AIRFLOW_USERNAME=<service-account>
AIRFLOW_PASSWORD=<host-local-secret>
```

GX project paths, Oracle/PostgreSQL credentials and the DataHub validation-action token belong in
the Airflow/GX worker secret environment, not the Web `.env`. If operators standardize names such
as `GX_CONTEXT_ROOT`, `GX_SOURCE_*` or `GX_DATAHUB_TOKEN`, those names are deployment conventions;
the current POC Web does not consume them.

## 6. End-to-end acceptance

- [ ] Native Oracle and PostgreSQL ingestion reports show the intended real source and profiling.
- [ ] DataHub UI and `/poc-api/datahub/profile-coverage` agree on profile coverage.
- [ ] One exact table detail shows the same row count/size and all schema fields in DataRiver.
- [ ] GX Checkpoint passes and fails on two controlled test cases without storing unexpected values.
- [ ] DataHub shows the GX Assertion against the exact Dataset URN.
- [ ] Airflow dispatch and callback use only the fixed DAG and service identity.
- [ ] Canonical DataRiver Run/result commit, retry and failure separation pass in the target stack.
- [ ] The quality dashboard is derived from authorized canonical results; missing results remain
      `UNKNOWN`, never a fabricated pass score.
