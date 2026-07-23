# ADR-0042: Typed BULK catalog metadata row and group contract

- Status: Accepted
- Date: 2026-07-23

## Context

The governed BULK path supports immutable CSV/XLSX evidence only for one dataset description per
row. Column descriptions and Domain/Tag/glossary-term changes update full DataHub Aspects. Treating
each source row as an independent CR would give several rows the same before-hash, create avoidable
conflicts and risk lost updates. A generic JSON candidate would also weaken the fixed mutation and
provenance boundary.

The initiating human may lose membership, operator eligibility or policy scope after approval but
before a worker reaches the provider. Existing generic apply code does not make the worker identity
a valid substitute for that human. Controlled metadata also cannot trust uploaded provider URNs;
it requires a workspace-owned canonical identifier.

## Decision

1. Keep `DATASET_DESCRIPTION_CSV_V1` and `DATASET_DESCRIPTION_XLSX_V1`, including V2 hashes and
   bindings, unchanged as compatibility profiles.
2. Add exactly `CATALOG_METADATA_ROWS_CSV_V1` and `CATALOG_METADATA_ROWS_XLSX_V1`. Their shared
   exact row schema and discriminators are specified in `docs/30_TYPED_BULK_CATALOG_METADATA_PRD.md`.
3. Persist new immutable source-row evidence, grouped candidate evidence and row membership in
   separate typed tables. Do not extend the V2 description table with generic nullable payload.
4. Group rows by dataset and fixed server-owned Aspect. One group creates one item and one CR.
   `schemaMetadata` therefore contains all column-description rows for the dataset; Tag/Term rows
   form one additive delta. Preparation publication is atomic, but file-wide provider application
   is not.
5. Upload rows identify Domain/Tag/Term vocabulary by workspace-scoped DataRiver UUID. A
   server-side resolver validates kind, lifecycle, workspace and visibility and derives the
   provider reference. Uploaded URNs, Aspect names and provider documents are invalid.
6. Bind profile, candidate kind, fixed Aspect, before hash, after hash and item-contract hash to
   the CR item in the same transaction. The DB boundary rejects substitution.
7. Before any provider call, reauthorize the initiating human and current local target. Revoked or
   drifted authority is terminal and produces no provider read/write.
8. Compile mutations only from typed evidence plus a fresh provider snapshot. Preserve unknown
   fields, do not rebase an approved after-document, serialize through the target-wide provider
   lock and require exact read-back.
9. Retain the current `schemaMetadata` field-description contract until external DataHub 1.6
   ownership evidence is available. A move to `editableSchemaMetadata` must change Manual and BULK
   together under a new ADR.
10. Physical dataset/field or vocabulary creation remains non-executable intake. Browser fan-out,
    multi-item apply and direct Airflow/DataHub mutation remain prohibited.

## Consequences

- Source row count and candidate count differ for the new profile, so consistency checks are
  version-specific.
- The separate evidence model costs more schema and migration work but avoids V2 type confusion
  and preserves historical verification.
- Provider URNs and credentials remain server-side. Vocabulary projection lifecycle and sync
  become explicit operational dependencies.
- A revoked request fails safely even after approval and must be resubmitted after authority is
  restored.
- DataHub 1.6 Aspect ownership/read-back, Airflow, object-store, WSL and multi-human evidence remain
  external release gates.
