# Reusable prompt — semiconductor seed initialization and DataHub evidence

You are operating the DataRiver local semiconductor value-chain seed workflow. Use the existing
`scripts/generate_semiconductor_seed.py`; do not hand-write thousands of DDL statements, create
browser mock data, or alter DataRiver application schemas.

1. Confirm PostgreSQL and the externally operated DataHub endpoint are healthy. Treat DataHub as
   an external metadata system, never as DataRiver's canonical business store.
2. Run the generator from the repository root with `--apply --confirm-reset --ingest-datahub
   --entity-scope dual`. Use only mounted/ignored secret files or environment references. Never
   echo, log, commit, or place a credential in a shell argument or YAML file.
3. Preserve the safety contract: it may reset only the `semiconductor_seed` schema after rejecting
   unexpected objects; keep rows/table in the 10–50 range; retain family-sized commits and bounded
   DataHub batches; do not change these limits to improve apparent throughput.
4. Report the physical PostgreSQL counts, the generated Oracle MOCK counts, and the exact DataHub
   entity count confirmed by read-back. State explicitly that Oracle is generated mock metadata,
   not a live Oracle ingestion.
5. If the generator or DataHub rejects a request, stop at the failed bounded step, retain the
   manifest/log evidence, diagnose the error without deleting unrelated objects, and rerun the
   same idempotent command only after correcting the cause.
6. For scheduled/manual orchestration, use only the paused-on-creation
   `datariver_semiconductor_seed_ingestion` Airflow DAG. Do not turn it into a recurring production
   schedule without an approved isolated non-production target.

Completion requires a generated `runtime/semiconductor-seed/manifest.json`, successful
PostgreSQL creation, and a 100% DataHub read-back for the selected scope. Clearly distinguish
completed evidence from any blocked external operation.
