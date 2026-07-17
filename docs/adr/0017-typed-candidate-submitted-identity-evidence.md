# ADR-0017: Typed candidate submitted-identity evidence

- Status: Accepted
- Date: 2026-07-17

## Context

ADR-0016 established an immutable typed BULK preparation boundary, but its first candidate row kept
only the local target asset ID, operation, exact proposed description and a V1 candidate hash. The
streaming parser also retained the submitted platform, database, schema and table values only in an
attempt-local draft. Neither the canonical candidate nor its V1 hash could later prove those four
submitted values.

The accepted object SHA-256 still binds the complete CSV, but a candidate API cannot reconstruct one
row's submitted identity from that digest. Reading the current catalog projection and labelling its
identity as the submitted CSV value would create false evidence, especially after catalog drift.

## Decision

Migration `0017` adds an explicit candidate evidence version and the submitted platform, database,
schema and table values plus a submitted-identity SHA-256. Existing `0016` candidates are preserved
as `LEGACY_V1`; their missing values are not backfilled from the current catalog. New rows default to
and must use `DATASET_DESCRIPTION_CANDIDATE_V2`. A database trigger rejects new legacy rows and all
candidate updates or deletes. No role receives an additional grant.

The CSV content profile and six-column schema remain `DATASET_DESCRIPTION_CSV_V1` because their
external byte shape has not changed. The registered parser version advances to
`dataset-description-csv-parser-v2`, changing the server configuration hash so a V1 preparation job
cannot be silently reused by a V2 publisher.

The submitted-identity hash binds the contract, workspace, target asset ID and all four submitted
identity fields. Candidate V2 then binds that identity hash together with the evidence version,
operation, profile/schema, workspace, target asset ID and exact proposed description. The ordered
candidate-root domain tag also advances to V2. Golden vectors freeze all three values.

A later read API must return the submitted fields as immutable evidence and the authorization-pruned
projection separately as `current_target`. It must never treat either as authority for execution.
Preview and change creation must re-resolve every target under the current subject, policy,
classification-access snapshot and active DATASET scope, and must fail closed when the submitted and
current identities no longer match.

## Consequences

- Upgrades retain honest legacy evidence without inventing hierarchy values.
- New candidate publication is incompatible with the old hash/root contract by design; parser and
  publisher version/configuration fences make that incompatibility explicit.
- Nullable submitted columns are required only to represent historical `LEGACY_V1` rows. The shape
  check and insert trigger require all submitted fields and their hash for every new V2 row.
- Downgrade is refused once a V2 candidate exists because discarding its submitted evidence would be
  destructive.
- Runtime preparation execution, candidate publication/read/preview and proposal creation remain
  disabled until the separate least-privilege worker identity, fenced atomic publish invariants,
  scanner/object-version evidence and current set-based authorization tests are complete.
