# Semiconductor seed workflow

## Purpose and boundary

This workflow supplies a realistic, large semiconductor value-chain topology for local DataHub
profiling and lineage demonstrations. It is not the smaller DataRiver application seed described
in [10_SEMICONDUCTOR_SEED.md](10_SEMICONDUCTOR_SEED.md), and it is never a source of business truth.

`scripts/generate_semiconductor_seed.py` owns exactly one external PostgreSQL schema:
`semiconductor_seed`. It has no access to DataRiver workspace tables, application domain tables,
or client/browser credentials. PostgreSQL is applied for real. Oracle is rendered as a clearly
labelled **MOCK** DDL and metadata artifact so a developer laptop can demonstrate cross-platform
catalog/lineage shapes without an Oracle server.

## Deterministic design

The plan contains 20 domain families and 25 semiconductor scenarios, producing 500 tables and 500
views per platform shape. Each table has 12–14 typed fields and 10–50 deterministic rows; the
default is 20. The relationship chain includes legal entity, facility, technology node, product,
supplier/qualification, procurement, material, logistics, inventory, equipment, routing,
operations, lots, quality, yield, costs, capital projects, and research/market signals. Foreign
keys connect the physical table layer and every view publishes the same dependency as DataHub
lineage.

With `--entity-scope dual`, the typed DataHub emitter registers:

| Platform | Tables | Views | Execution mode | Dataset entities |
| --- | ---: | ---: | --- | ---: |
| PostgreSQL | 500 | 500 | `APPLIED` | 1,000 |
| Oracle | 500 | 500 | `MOCK` | 1,000 |
| Total | 1,000 | 1,000 | Explicitly distinguishable | 2,000 |

No Oracle metadata is described as a live database scan. Each mock entity carries the custom
property `datariver.seed.execution_mode=MOCK`.

## Guardrails and restart semantics

- The generator accepts values only in the 10–50 rows/table range. It does not create unbounded
  insert volumes.
- PostgreSQL work is committed one 25-table family at a time. Inserts are one small table batch,
  and table/view/DataHub progress is printed continuously.
- A rerun enumerates objects in `semiconductor_seed`. It refuses to reset unknown tables/views. If
  the expected seed objects exist, `--confirm-reset` is required before issuing its explicit
  `DROP VIEW IF EXISTS ... CASCADE` and `DROP TABLE IF EXISTS ... CASCADE` sequence.
- The output manifest and Oracle mock DDL are generated below ignored
  `runtime/semiconductor-seed/`. No real credentials, rows, or DataHub token are written there.
- DataHub messages are fixed, typed dataset-aspect UPSERTs with deterministic idempotency keys.
  Every entity gets `datasetProperties` and `upstreamLineage`; real PostgreSQL tables also get
  `schemaMetadata` for profiling. The controlled glossary/tag vocabulary is seeded before any
  dataset, and every dataset receives family/scenario/provenance tags and terms. Every generated
  PostgreSQL, view and clearly labelled Oracle MOCK field receives cross-cutting semantic
  tags/terms in `schemaMetadata`, so the catalog, registration and change-management screens show
  the same controlled metadata. The browser is not involved.
  Transient `429`/`5xx` calls retry at most four times; a hard failure stops the run for a safe rerun.

## Local execution and evidence

Start the host-development PostgreSQL and external DataHub as described in the root README. From
the repository root, run:

```powershell
.\.venv\Scripts\python.exe .\scripts\generate_semiconductor_seed.py `
  --apply --confirm-reset --ingest-datahub --entity-scope dual
```

For the validated Mac Compose topology, use its already-started Airflow service to run the same
manual-only workflow. The Airflow entrypoint wrapper is required because Compose `exec` bypasses a
service's configured entrypoint and Airflow obtains its database/API secrets there.

```bash
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml \
  exec airflow-api-server /bin/bash /opt/datariver/airflow-entrypoint.sh \
  dags unpause datariver_semiconductor_seed_ingestion
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml \
  exec airflow-api-server /bin/bash /opt/datariver/airflow-entrypoint.sh \
  dags trigger datariver_semiconductor_seed_ingestion
# After the run is SUCCESS, return the manual-only DAG to its default pause state.
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml \
  exec airflow-api-server /bin/bash /opt/datariver/airflow-entrypoint.sh \
  dags pause datariver_semiconductor_seed_ingestion
```

The defaults resolve only the following local secret files: `secrets/postgres_password` for the
`datariver_owner` PostgreSQL role and `secrets/datahub_token` for DataHub. Override endpoint,
database, role, or secret-file paths with named flags or `SEMICONDUCTOR_POSTGRES_*` /
`DATAHUB_*` environment variables. Do not put secret values in an argument, recipe, log, or Git.

On success, inspect `runtime/semiconductor-seed/manifest.json`. It records the intended physical
counts, controlled vocabulary expected/verified counts, and typed read-back for each generated
dataset URN, tag/term association, and enriched PostgreSQL table field. The successful direct
read-back count is the reportable DataHub entity count; a submitted HTTP proposal alone is not
acceptance evidence. The detailed controlled vocabulary and standalone/restartable verification
commands are in [the semiconductor governance taxonomy](18_SEMICONDUCTOR_GOVERNANCE_TAXONOMY.md).

For a source-native rescan rather than deterministic metadata emission, provide secrets only via
the execution environment and run the reviewed DataHub CLI installation with
`infra/datahub/recipes/semiconductor_postgres.yml`. That recipe profiles only `semiconductor_seed`,
includes views and view lineage, limits workers to four, and suppresses field min/max values. It is
an optional complement, not a replacement for the generator's exact entity verification.

## Airflow workflow

The `datariver_semiconductor_seed_ingestion` DAG is manual-only, paused on creation, single-active
run, retry-once and limited to three hours. It invokes the same generator in the Airflow image using
mounted secret files and the private Compose PostgreSQL network, then calls the bounded
`datariver_catalog_sync` reconciliation through the Airflow service account. This makes generated
DataHub entities visible in DataRiver's local projection without copying DataHub credentials to the
browser. Its only permitted runtime parameters are:

- `rows_per_table`: integer from 10 through 50; defaults to 20.
- `entity_scope`: `postgres` or `dual`; defaults to `dual`.

Build/start Airflow only after the core stack is healthy, then trigger the DAG from the Airflow UI
or its local CLI. The exact command follows the repository's overlay convention:

```bash
scripts/compose.sh --env-file .env -f compose.yaml -f compose.airflow.yaml \
  up -d --build --wait
scripts/compose.sh --env-file .env -f compose.yaml -f compose.airflow.yaml \
  exec airflow-api-server \
  airflow dags unpause datariver_semiconductor_seed_ingestion
scripts/compose.sh --env-file .env -f compose.yaml -f compose.airflow.yaml \
  exec airflow-api-server \
  airflow dags trigger datariver_semiconductor_seed_ingestion
```

Use the DAG log and its generated manifest as evidence. A failed manual run can be run again: it
resets only its owned schema and repeats idempotent DataHub proposals. Do not schedule it on a
shared environment without an approved non-production database and DataHub namespace.

## Reusable execution prompt

A strengthened human/LLM handoff prompt for future initialization is maintained at
[prompts/SEMICONDUCTOR_SEED_EXECUTION_PROMPT.md](prompts/SEMICONDUCTOR_SEED_EXECUTION_PROMPT.md).
It preserves the database/DataHub boundary, explicit Oracle-MOCK disclosure, required evidence,
and the no-secret/no-browser constraints.
