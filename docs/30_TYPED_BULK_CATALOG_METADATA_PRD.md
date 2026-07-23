# Typed BULK catalog metadata rows PRD

## Scope and outcome

This work package closes the source-local portion of backlog item `R3-07`. It extends the existing
immutable upload → preparation receipt → candidate → preview → one governed Change Request flow.
It does not add direct DataHub writes, browser-supplied provider documents, physical table/column
creation, multi-candidate fan-out or multi-item apply.

The existing `DATASET_DESCRIPTION_*_V1` profiles remain the immutable compatibility contract for
one table description per row. New metadata uses exactly two transport profiles:
`CATALOG_METADATA_ROWS_CSV_V1` and `CATALOG_METADATA_ROWS_XLSX_V1`. Both have this exact header:

`record_kind,asset_id,platform,database_name,schema_name,table_name,field_path,operation,value_text,controlled_ref`

The discriminated row contract is:

| `record_kind` | Operation and shape | Server-owned Aspect |
|---|---|---|
| `TABLE_DESCRIPTION` | `SET` with `value_text`, or `CLEAR`; no field/ref | `datasetProperties` |
| `COLUMN_DESCRIPTION` | `SET` with `value_text`, or `CLEAR`; exact existing `field_path` | `schemaMetadata` |
| `DATASET_DOMAIN` | `SET` with one local vocabulary UUID, or `CLEAR` | `domains` |
| `DATASET_TERM` | `ADD` with one local vocabulary UUID | `glossaryTerms` |
| `DATASET_TAG` | `ADD` with one local vocabulary UUID | `globalTags` |

`controlled_ref` is a workspace-scoped DataRiver vocabulary UUID. Provider URNs, Aspect names and
documents are not upload fields. A server-side resolver checks the vocabulary kind, lifecycle,
workspace and current visibility, then derives the provider reference.

## Evidence and grouping

- Source rows are immutable V3 evidence under `CATALOG_METADATA_CANDIDATE_V3`. Their row hash binds workspace,
  registered profile/schema/configuration, source ordinal, submitted hierarchy, row kind,
  operation, field/value or local vocabulary ID.
- Rows are grouped by `(workspace, target asset, fixed Aspect)`. A group uses the same immutable
  V3 evidence contract and stores its ordered row membership/root.
- One candidate group creates exactly one server-authored Aspect item and one Change Request.
  Multiple column rows for one dataset therefore compile into one full-schema mutation; Tag or
  Term rows compile into one current-set-plus-additions mutation.
- `item_count` is source-row count; `candidate_count` is Aspect-group count. The compatibility V2
  profile retains its historical one-row/one-candidate equality.
- Duplicate semantic targets and conflicting operations are rejected as a whole. Rows for the
  same `(asset, fixed Aspect)` may be non-contiguous; the parser merges them into one candidate
  while preserving their original source ordinals in ordered membership evidence. Preparation
  publication is atomic; applying every group from a file is not claimed to be file-atomic.

## Security and execution invariants

- Profile selection is explicit. Filename or MIME cannot infer mutation authority.
- Files remain at most 16 MiB, 10,000 rows and 64 KiB per logical row. XLSX retains bounded
  ZIP/XML/spool protections and rejects formulas, active content, links and hidden ambiguity.
- Parsed candidates use ADR-0041's fixed 64 MiB attempt spool. CSV/XLSX parsing retains only
  canonical grouped row evidence, and publication replays the spool in bounded batches instead of
  materializing the whole candidate graph.
- Existing V2 evidence, hashes, roots and bindings remain byte-for-byte compatible. New evidence
  uses separate immutable row/group/membership evidence plus binding metadata rather than nullable
  generic provider payloads.
- Preparation resolves only existing ACTIVE datasets in bounded set-based batches. Submitted
  hierarchy must exactly match the current projection. Column paths and vocabulary references are
  live-resolved; denied, missing, duplicate or drifted data fails without disclosing the row.
- Preview reauthorizes, reads the fixed Aspect and preserves unknown provider fields. A column
  path must match exactly once. Tags/terms add to the fresh current set; no approved document is
  silently rebased after preview.
- Create accepts only candidate ID, quoted preview ETag, title, reason and an idempotency key. It
  re-runs preview, locks the current target and atomically binds candidate, fixed Aspect,
  before/after hashes, item-contract hash, one item, one CR and outbox evidence.
- Preparation performs an early authorization rejection, locks current targets/vocabulary, then
  repeats a transaction-locking authorization check immediately before receipt publication.
  Concurrent membership/policy/generation/grant/target revocation therefore linearizes before or
  after a publication transaction rather than between authorization and persistence.
- Provider apply first reauthorizes the initiating human's active membership, operator
  eligibility, policy/classification/System/Domain scope and current target. The worker identity
  never substitutes for the human. Revocation produces zero provider calls.
- Apply re-reads the Aspect under the provider-wide target lock, reconciles `current == after`,
  rejects `current != before`, performs a typed write and requires exact hash read-back.
- Raw provider response/documents, object coordinates, credentials and client-selected target URNs
  never cross into the browser or upload contract.

## Ownership decisions

- `datasetProperties`, `domains`, `globalTags` and `glossaryTerms` remain governed catalog
  enrichment Aspects.
- Column description retains the currently accepted `schemaMetadata` contract for compatibility,
  but external DataHub 1.6 validation must prove that ingestion ownership will not erase or
  overwrite enrichment. If the target requires `editableSchemaMetadata`, Manual and BULK must
  migrate together under a new ADR; the source build cannot silently switch one path.
- Creating a physical dataset/field or a vocabulary entity is intake-only and outside this
  executable profile.

## User experience

- The BULK selector presents a semantic profile and a CSV/XLSX format, then downloads a
  server-versioned header-only template.
- Validation returns a bounded scalar summary; row errors use a separate cursor page and never
  echo full sensitive rows.
- Candidate pages are keyset-bounded and show the server discriminator, target, operation count,
  field/reference summary and classification without provider documents.
- One explicit command creates one CR. The UI never loops over a page and never claims that a
  whole file has been applied. Lost responses reuse the same idempotency key while candidate,
  title and reason are unchanged.

## External gates

Source completion does not prove the preparation PC. External Airflow OIDC execution, target
MinIO/S3 immutable-read behavior, DataHub 1.6 Aspect ownership/apply/read-back, real
Admin/Data-Steward/approver identities, representative full-worker 10,000-row load/crash/retry
evidence and WSL x86_64 operation remain `EXTERNAL_GATE`. The source-local parser does have a
10,000-row peak-memory regression; it is not a target-host soak claim.

## Acceptance checklist

- [x] `TB-01` Register the two exact wide-row CSV/XLSX profiles and header-only templates without
  MIME inference.
- [x] `TB-02` Parse every positive row kind into deterministic profile-bound CSV/XLSX row and
  grouped-candidate hashes.
- [x] `TB-03` Reject shape/control/UUID/header/duplicate/conflict and existing byte/ZIP/XML attacks.
- [x] `TB-04` Add separate immutable row/group/membership evidence and binding metadata, migration, RLS,
  immutability and grants while preserving V2.
- [x] `TB-05` Publish a complete row/group set under the current lease; verify identities,
  vocabulary and column paths before READY.
- [x] `TB-06` Revalidate receipt, row/group roots, membership and current authorization on every
  bounded page/read.
- [x] `TB-07` Compile all five row kinds through fixed server mappings while preserving unknown
  provider fields.
- [x] `TB-08` Atomically bind one candidate to one fixed Aspect item/CR with before, after and
  item-contract hashes.
- [x] `TB-09` Reauthorize the initiating human and current local target immediately before every
  provider read/write; prove revocation causes zero calls.
- [x] `TB-10` Expose bounded typed API/UI states with no provider payload, target URN, Aspect or
  fan-out input.
- [x] `TB-11` Prove no-op, stale-before, concurrent writer, ambiguous completion, read-back and
  retry behavior for every fixed Aspect.
- [x] `TB-12` Pass deterministic migration, empty/current PostgreSQL, strict backend and full
  frontend gates.
- [x] `TB-13` Close independent data/security/UI/SW-quality P0/P1 findings and record P2 decisions.
- [x] `TB-14` Create focused local commits; remote push remains blocked until its exact
  destination is explicitly approved.
- [x] `TB-15` Report all target-environment evidence honestly as `EXTERNAL_GATE`.

Local implementation commit: `39d20d0`. Independent security/data and App/API/UI reviews reported
no remaining P0/P1. Candidate-table typography at authenticated reference viewports, WSL amd64,
external providers, real multi-actor identity and representative full-worker load/recovery remain
explicit external gates.
