# Migration governance and accepted-history integrity

## Purpose

The 54-file Migration P0 review recorded in
[`67_MIGRATION_P0_EXACT_INVENTORY.md`](67_MIGRATION_P0_EXACT_INVENTORY.md) is a one-time
remediation for the proven historical blanket fail-open rewrite. It is not the normal review model
for every release. Accepted historical Alembic migrations are immutable: an accepted revision may
not be silently rewritten, renamed, deleted, or replaced after deployment evidence exists.

`backend/alembic/accepted_migration_checksums.json` is the machine-readable accepted-history
manifest. `scripts/verify_static.py` rejects a changed or missing accepted migration and any new,
unmanifested migration file. The manifest is updated only as part of an explicitly reviewed
migration change. Updating a checksum never substitutes for the compatibility and failure-state
evidence below.

## Bounded review model

| Change | Required review and evidence |
| --- | --- |
| No migration source change | Checksum/static verification and a representative supported-revision upgrade smoke. Do not repeat the historical 54-file audit. |
| New migration | Review only the new revision and its dependencies; prove previous-revision compatibility, fresh canonical baseline-to-head, accepted-like existing-state-to-head, and fail-closed partial/malformed states. Add the new file and digest to the manifest in the reviewed change. |
| Accepted historical migration edit | Exceptional written justification, exact affected-family audit, definition-level compatibility evidence, and manifest update. Never use a blanket rewrite or treat the new digest as sufficient evidence. |
| Baseline/framework/integrity/support-policy change | A broad audit is required only when the squashed baseline, migration framework, checksum/integrity mechanism, or supported historical revision policy changes. |

Every compatibility classifier follows the same state contract:

1. Exact canonical pre-existing state: safely continue or perform the documented idempotent
   reassertion.
2. Expected object absent: run the migration normally.
3. Partial, malformed, or unexpected state: fail closed with the migration's typed
   `RuntimeError`; do not log-and-continue.

Definition-sensitive families compare normalized constraints, index uniqueness and predicates,
RLS policy command/roles/permissiveness/USING/WITH CHECK, trigger definition/function/enabled
state, and RLS enable/force state. Object names alone are not canonical evidence.

## POST-PREP backlog

`MIGRATION_BASELINE_V2_AND_LEGACY_RETIREMENT` is deliberately not part of the PREP hotfix. It is
gated until PREP and OPS acceptance, and requires separate user approval. Its design review must
define:

- the baseline-V2 cutover revision and supported historical revisions;
- the fresh-install baseline strategy and legacy migration retention period;
- archive/removal conditions and the checksum policy after cutover;
- oldest-supported-revision upgrade tests;
- target-local backup, rollback, and recovery evidence.

No current migration is deleted, reorganized, or retired by this backlog record.
