# ADR-0021: Airflow-owned application of immutable Manual metadata receipts

- Status: Accepted
- Date: 2026-07-18
- Refines: ADR-0005, ADR-0008, ADR-0015

## Context

The v0.3 MANUAL workbench was a direct browser-to-provider workflow.  DataRiver v1 instead records
an authorized table/column Description, Domain, Tag and Term edit as a private CSV receipt in the
deployment-owned InfoSchema bucket and as an immutable PostgreSQL submission.  The workflow must
apply the same receipt to DataHub without exposing an object key, a provider credential or an
Airflow control endpoint to the browser, and it must distinguish a provider acceptance from a
verified provider result.

## Decision

`datariver_manual_metadata_apply` is a paused-by-default, bounded Airflow DAG.  It obtains only a
short-lived OIDC client-credentials token and calls a service-account-only DataRiver API entry point
under `catalog.sync`; a normal registration user does not receive that action.  Airflow has neither
the DataHub token nor object-store credentials.  DataRiver owns the private object read and the
DataHub adapter invocation.

For each leased submission, the application:

1. streams at most 5 MiB from the private `UPLOAD_METADATA_MANUAL_YYMMDD_SERIAL.csv` receipt,
   verifies its SHA-256, size, row count and typed table/column contents against the immutable
   database record;
2. reads each allowed DataHub aspect (`datasetProperties`, `domains`, `globalTags`,
   `glossaryTerms`, `schemaMetadata`), merges only the typed fields, submits with a stable
   per-submission/per-aspect idempotency key, then reads the aspect again and compares its canonical
   hash; and
3. marks the submission `APPLIED` only after every aspect read-back matches.  Leases, attempts and
   retryable/terminal failure codes are durable.  A partial provider success is safe to resume:
   already matching aspects are skipped and no aspect is treated as complete merely because a POST
   returned success.

The typed apply surface replaces values rather than unioning them; this is the explicit Save state
shown to the user.  It does not create arbitrary provider entities, accept raw aspects, run
arbitrary Airflow DAGs, or permit a browser/admin bypass.  A newly typed value is an association
intent; an environment must provision the corresponding controlled-vocabulary entity through its
approved DataHub governance process before the apply can succeed.

## Consequences

- The application and Airflow deployment must set `S3_BUCKET_INFOSCHEMA`; no default bucket name is
  selected in code.  Migration `0024` is required before the API reports ready.
- The DataHub service principal requires the reviewed v1.6 contract's typed aspect write/read
  permissions.  Its credentials remain mounted only in DataRiver.
- A stale/altered receipt, provider schema drift, missing vocabulary entity or read-back mismatch
  produces a visible `FAILED`/retry state and never a false `APPLIED` state.
- Target acceptance still requires a real Airflow-to-DataRiver OIDC run, MinIO/SeaweedFS receipt
  read, DataHub v1.6 aspect application/read-back and worker lease/retry crash evidence.
