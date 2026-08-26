# DataHub Inventory Scroll / Entity Extraction Evidence

Recorded at `2026-08-26T08:04:19Z` for Product
`1e9574d6af42b6bff6826e2352601c0c8891e572`.

## Root cause

The provider request itself completed, but the Product rejected a later page in
`ENTITY_EXTRACTION`. The old `datahubCatalogPage` required
`ScrollResults.count === searchResults.length`. DataHub's resolver maps `count` from provider
page-size metadata, so a cursor-driven partial terminal page can legitimately contain fewer
materialized `SearchResult` envelopes. That deterministic mismatch was converted to
`PREP_DATAHUB_INVENTORY_CONTRACT_FAILED` after every earlier page had reconciled correctly.

The inventory request also omitted the stable sort required by DataHub for a complete deep scroll.
The corrected request uses:

```text
sortInput.sortCriteria = [{ field: urn, sortOrder: ASCENDING }]
```

## Corrected accounting contract

The raw unit is the received `SearchResult` envelope, not `ScrollResults.count` and not only a
successfully materialized entity:

```text
raw_search_result_count
= normalized_current_count
 + filtered_noncurrent_count
 + deduplicated_count
 + unresolved_search_result_count
 + other explicitly classified bounded exclusions
```

`provider_total` is observed dynamically and completeness requires
`raw_search_result_count == provider_total`. Canonical current count remains independently derived.

The successful unresolved bucket is currently zero. DataHub's GraphQL schema declares
`SearchResult.entity` non-null, so an absent/null entity is a terminal
`SEARCH_RESULT_ENTITY_ABSENT` contract violation rather than an accepted exclusion. A valid Dataset
URN/type with no current properties or schema aspect remains the bounded non-current reason
`DATASET_CURRENT_ASPECTS_ABSENT`.

Exact sanitized extraction reasons are:

- `PAGE_RESULT_COUNT_CONTRACT`
- `SEARCH_RESULT_ENVELOPE_INVALID`
- `SEARCH_RESULT_ENTITY_ABSENT`
- `SEARCH_RESULT_ENTITY_TYPE_INVALID`
- `SEARCH_RESULT_DATASET_URN_INVALID`
- `DATASET_CURRENT_ASPECTS_ABSENT`

No URN, provider response body, URL, credential, token, or optional metadata value is logged.

## Smoke/deploy classification

The smoke runner and deploy wrapper now share a bounded allowlist for all six Product inventory
failure codes. A valid `PREP_DATAHUB_INVENTORY_*` code is retained through the Product response,
`smoke-failure.json`, and final `PrepError`; an unknown inventory-shaped string is rejected.
Deterministic extraction, normalization, GraphQL-contract, and promotion failures remain terminal
and fail fast. Only query/page transport failures retain bounded readiness retry.

## Generic regression

Tests use only page-size-relative generated counts, cursor termination, and arbitrary remainders.
They cover empty, boundary-minus-one, exact boundary, boundary-plus-one, multi-page, partial terminal,
large bounded rich metadata, sparse/null optional fields, Table/View, missing hierarchy,
non-current records, identical duplicates, malformed envelopes, null entity, wrong type, invalid URN,
normalization failure, persistence/promotion, current Resource Tree, and bounded Catalog response.

- Runtime PREP-specific counts: **NONE**
- Test PREP-specific counts: **NONE**
- Runtime fixed PREP page count: **NONE**
- Test fixed PREP page count: **NONE**

## Verification

- Inventory focused: `5/5 PASS`
- Smoke focused: `13/13 PASS`
- Node Product server: `137/137 PASS`
- UI: `90 files / 663 tests PASS`
- lint / typecheck / production build / POC build: `PASS`
- Ruff: `PASS`
- strict mypy: `PASS` (`578` source files)
- static verification: `PASS`
- PREP deploy unit/handoff: `42/42 PASS`
- Docker fresh/existing/residual state matrix: `PASS`
- forced smoke failure to same-command resume: `PASS`
- exact linux/amd64 OCI revision: `PASS`
- image runtime proxy environment leakage: `NONE`
- Product/test PREP-specific numeric constants: `NONE`

The exact PREP operator command remains:

```bash
./scripts/prep39083 deploy
```

The existing owned `SMOKE_FAILED` attempt is resumable without volume deletion, database reset,
runtime-secret removal, attempt-receipt deletion, or manual container recreation.

Actual PREP deployment: **NOT EXECUTED by the DEV Agent**.

