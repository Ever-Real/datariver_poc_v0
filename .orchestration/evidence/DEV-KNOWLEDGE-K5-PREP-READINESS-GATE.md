# DEV Knowledge K5 — PREP Deployment Readiness Gate

- Scope: deployment-readiness only. K5 Product source was not changed, full regression was not
  repeated, and K6 was not started.
- Product / running DEV OCI: `34af2b869d04fd96f4b9cd69f6eeed8729bafe28` (exact); Web
  `/healthz` returned `ok` after cleanup and Web-only recreation.
- K5 status remains `COMPLETE_RUNTIME_VERIFIED`. PREP gate status is
  `K5_PREP_DEPLOYMENT_NOT_READY`.

## Blocking relation projection result

A disposable published release used two Classes (`Person`, `Asset`), one valid directed T-Box
relation (`OWNS`) and one canonical source row containing both exact SUBJECT_ID fields. The actual
browser Data Enricher produced two independent previews:

- `Person`: Node 1 / Relation 0 / Rejected 0 / Unmapped 0.
- `Asset`: Node 1 / Relation 0 / Rejected 0 / Unmapped 0.
- confirm-before-write check: scoped Neo4j Node 0 / Edge 0.

The required combined preview Node 2 / Relation 1 was therefore not available. Confirm, projection
and replay were intentionally not run: a Node 1 / Relation 0 execution would not validate the
relation path. Narrow contract inspection confirms the current bounded planner accepts exactly one
source mapping target and emits an empty edge list. No K5 source repair was attempted in this gate.

Backlog gate: `K5_PREP_RELATION_PROJECTION_REQUIRED` — implement one bounded release/source-row
plan that resolves both relation endpoints, previews Node 2 / Relation 1, preserves exact relation
provenance, and proves projection/replay Node 2 / distinct Edge 1. Rerun focused K5 tests and this
single runtime fixture only; run full suites only if Product source changes.

## Cleanup

- Deleted the exact two READY preview jobs and one `k5-relation-dev-v1` source row.
- Scoped Neo4j read/delete returned Node 0 / Edge 0 / deleted 0.
- Archived disposable Asset `K5 Relation E2E 20260819`.
- Disabled both disposable credentials and revoked both sessions.
- Removed the temporary runtime manifest, recreated Web only, and deleted isolated browser profiles.
- The four untracked Gemini handoff artifacts remain preserved and are not Product/Evidence inputs.

## `POC_KNOWLEDGE_SOURCE_MANIFEST` contract

- Value: optional environment **string** containing a JSON object keyed by exact canonical DataHub
  Table URN. Each entry requires bounded non-empty string fields `manifest_ref`, `source_version`
  and `secret_ref`.
- Timing: parsed once at Node process startup. Empty is allowed while K5 is unused; malformed
  non-empty JSON fails startup. K5 preview fails closed if the map, exact Table entry or referenced
  canonical source rows are absent.
- Reference semantics: it is not a file path. `manifest_ref` selects rows already stored in
  `poc_knowledge_source_rows`; `secret_ref` is an opaque non-secret reference recorded in
  provenance and is not dereferenced by the current fixed-function planner. Secret values must not
  be stored in the manifest or PostgreSQL.
- Compose passes the string from its chosen env file. The DEV `deploy/poc/.env` is an ignored,
  mode-0600 regular file inside this worktree, not a stable external PREP contract. A clean Product
  worktree will not create it. The actual PREP env/secret absolute external path cannot be verified
  from this DEV host and is `PREP_EXTERNAL_ENV_CONTRACT_RECHECK_REQUIRED`; never copy the DEV env.

## PREP migration gate

Migration: `deploy/poc/postgres-init/002-poc-knowledge-ingestion.sql`; transactional, additive,
idempotent only for a compatible schema, no automatic down migration.

Before G3, capture an approved database backup/rollback point and check both names with
`to_regclass('public.poc_knowledge_ingestion_jobs')` and
`to_regclass('public.poc_knowledge_source_rows')`. If either exists, compare it to the exact
definitions below before applying; `IF NOT EXISTS` alone is not compatibility evidence.

Post-apply read-only verification must compare `information_schema.columns`, `pg_constraint` and
`pg_indexes` against:

- `poc_knowledge_ingestion_jobs`: 16 columns; PK `job_id`; unique
  `(draft_id, release_id, idempotency_key)`; checks
  `ck_poc_knowledge_ingestion_job_hash`, `_state`, `_versions`, `_bounds`; allowed states
  `PREPARING`, `READY`, `CONFIRMED`, `DRAFT_CHANGESET_READY`, `PROJECTED`, `FAILED`.
- `poc_knowledge_source_rows`: 7 columns; PK `(manifest_ref, row_key)`; checks
  `ck_poc_knowledge_source_row_hash`, `_bounds`; index
  `ix_poc_knowledge_source_rows_asset(manifest_ref, asset_urn, source_version, row_key)`.

Any missing, extra-in-contract, differently typed, nullable/default, key, check or index mismatch is
a migration conflict and must stop deployment. Backup restore is the DB rollback authority because
no down migration exists.

## Correct approval gates and deployment outline

- `READ_ONLY`: DEV status/branch/HEAD/log/diff/remote checks; PREP repo path, status, branch, HEAD,
  current OCI revision/digest, env/secret path, schema metadata and backup inventory; PREP
  `git fetch`, log and rev-parse.
- `G1/G2_REQUIRED`: DEV push of the approved branch/commit after fetch/divergence checks. Never
  force-push; do not push ignored env/secrets, Gemini artifacts, local dashboards or test data.
- `G3_REQUIRED`: every PREP source mutation (`pull`, checkout, worktree activation), migration,
  build, Web recreate/deploy, and K5 write validation.

PREP deployment remains blocked until the relation gate passes and the actual external PREP
env/secret contract is recorded. When those gates pass, use the exact approved Product commit,
require PREP Git HEAD = built OCI revision = running OCI revision, and recreate only Web after the
migration. G3 write validation must use a disposable Asset/source and clean it up.

Rollback authority must be captured immediately before PREP mutation from the actual PREP host:
previous PREP Git SHA, running OCI revision and image digest, plus the DB backup point. The DEV SHA
`93868...` is not an executable PREP rollback target. Roll back Web using the recorded prior image
and deployment procedure; restore DB only under the approved backup/restore contract. Do not use
`git reset --hard`, delete volumes, reset DB, or delete Neo4j globally.

Independent validator remains `K5_VALIDATOR_PENDING_RESOURCE` and may be run at most once when the
resource recovers. It does not justify repeating already-passed K5 suites/runtime checks.
