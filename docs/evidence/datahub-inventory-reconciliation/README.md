# DataHub current-inventory reconciliation correction

## Accepted input evidence

The PREP operator executed the exact rich `datahubEmbeddingInventoryQuery` from the running Product
through the same provider transport. The observed PREP provider total was 2,036 Dataset search
results over nine successful cursor pages. Every page returned HTTP 200, the cursor walk completed,
and GraphQL returned no errors. These two numbers are diagnostic evidence only: neither appears in
Product runtime logic or Product tests.

The healthy provider walk closed URL, token, network, proxy/NO_PROXY, GraphQL, query-contract and
cursor-pagination investigation. No provider environment or query change was made.

## Root cause and exact failing boundary

The failing Product boundary was `INVENTORY_VALIDATION`, after rich page retrieval and Dataset
normalization. The previous reconciler filtered non-current/aspect-less Dataset shells and removed
duplicate canonical URNs before validating completeness, then incorrectly required the resulting
unique current count to equal DataHub's raw provider `total`. A complete raw cursor walk therefore
failed whenever at least one provider result was classified out of the current projection or
canonical deduplication reduced the current item count.

That explains why all rich PREP pages could succeed while `/poc-api/datahub/catalog?limit=1`
returned 5xx: the failure was the local terminal count invariant, not provider retrieval. The prior
smoke wrapper mapped every non-2xx Catalog response to
`PREP_SMOKE_DATAHUB_CONNECTIVITY_FAILED`, discarded the internal boundary, then polled through the
refresh cooldown.

## Corrected dynamic contract

The runtime now observes `provider_total` from the first DataHub page and verifies it remains stable.
It separately accounts for:

```text
raw_processed_count
= normalized_current_count
 + filtered_noncurrent_count
 + deduplicated_count
```

The currently defined bounded exclusion is `DATASET_CURRENT_ASPECTS_ABSENT`, matching the existing
current Dataset predicate after canonical URN and `DATASET` type validation. Null/absent optional
description, hierarchy, domain, tag, term, owner, custom/structured property, profile and schema
field metadata is accepted. Malformed identity or invalid metadata shape fails with its exact phase;
no Dataset is silently dropped and no missing hierarchy value is fabricated.

Cursor termination and completeness use only the dynamically observed total, raw result count and
provider cursor. Runtime PREP-specific Dataset count: **NONE**. Runtime fixed page count: **NONE**.
Canonical current count is independently derived. DEV and OPS inventories are independent of PREP.

## Sanitized diagnostics and retry behavior

The current projection path reports only bounded diagnostics: phase, page ordinal, raw processed and
expected counts, normalized/non-current/duplicate counts, exclusion reason, safe timing fields,
HTTP status class and error class. It never reports provider bodies, credentials, tokens or entity
URNs. The observable phases are:

1. `PAGE_FETCH`
2. `ENTITY_EXTRACTION`
3. `ENTITY_NORMALIZATION`
4. `INVENTORY_VALIDATION`
5. `DEDUPLICATION`
6. `SNAPSHOT_PERSISTENCE`
7. `SNAPSHOT_PROMOTION`
8. `AUTHORIZATION_PROJECTION`
9. `RESPONSE_BUILD`

Typed failures are:

- `PREP_DATAHUB_INVENTORY_QUERY_FAILED`
- `PREP_DATAHUB_INVENTORY_PAGE_FAILED`
- `PREP_DATAHUB_INVENTORY_GRAPHQL_FAILED`
- `PREP_DATAHUB_INVENTORY_CONTRACT_FAILED`
- `PREP_DATAHUB_INVENTORY_NORMALIZATION_FAILED`
- `PREP_DATAHUB_INVENTORY_PROMOTION_FAILED`

Query/page transport failures remain bounded and retryable. GraphQL contract, extraction,
normalization, validation, deduplication and promotion failures are terminal and fail fast through
the cooldown with their original sanitized phase. Smoke now performs an authorization-aware current
root refresh before the bounded Catalog read, so a stale LKG cannot by itself accept a new release.
The last valid projection remains available to ordinary Product reads when a background refresh
fails.

## Generic regression

The test obtains the provider page size from the Product request contract and generates boundary
vectors for zero, one, page-size minus one, exact page size, page-size plus one, and multiple pages
with an arbitrary remainder. A separate large generated rich inventory combines sparse/null
optional metadata, empty collections, Table/View subtypes, missing hierarchy, varied governance
metadata, schema fields, two explicitly non-current aspect shells and one identical canonical
duplicate. It exercises the real fixed rich query, HTTP provider cursor walk, Product normalization,
accounting, deterministic ordering, durable snapshot write, authorization projection, response
build and `/poc-api/datahub/catalog?limit=1`.

The large generated case reproduces the same accounting condition observed on PREP without using
the PREP count or page count. Test PREP-specific Dataset count: **NONE**. Test fixed PREP page count:
**NONE**. The actual PREP observation (2,036 results, nine pages) remains evidence text only.

## Verification

- Generic inventory/diagnostic focused suite: 4/4 PASS.
- PREP smoke classification/progress suite: 5/5 PASS.
- Node Product server full suite: 136/136 PASS.
- Catalog LKG and cursor-boundary focused regression: 2/2 PASS.
- UI full suite: 90 files / 663 tests PASS.
- ESLint, TypeScript, standard build and POC build: PASS.
- Ruff: PASS; strict mypy: 579 source files PASS; static verification: PASS.
- PREP deployment/handoff unit contract: 35/35 PASS.
- Isolated fresh/running/stopped/rerun/residual/ambiguous/39080 state matrix: PASS in 205.58s.
- Isolated forced-smoke-failure then same-command owned-incomplete resume: PASS in 203.29s.
- Compose parse, diff-check and source/test PREP-count scan: PASS.
- Image secret/build-proxy leak scan: PASS.

## Exact DEV Product runtime

- Product: `d69c582867e7666b763bed67dc6def257ea6b909`.
- Image: `datariver-poc:d69c582867e7666b763bed67dc6def257ea6b909`.
- Image ID: `sha256:edf4ae18674d25f784cde8972653d6c3649796ba61463b0f1888bdab7ffd2817`.
- Platform: `linux/amd64`; OCI revision exactly matches Product.
- 39083: HTTP 200, healthy, restart count 0.
- 39090: HTTP 200.
- 39080: unchanged and down.
- DEV durable canonical current inventory count: 2,003, independently observed from the DEV state
  projection; it was not assumed from PREP.

The DEV agent did not execute PREP or OPS deployment.

