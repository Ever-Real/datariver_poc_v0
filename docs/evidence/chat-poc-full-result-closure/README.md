# Chat POC Full-Result Runtime Closure

## Scope and status

This Evidence binds the cumulative Product
`567da6ba6e11f5b72126dffa3ccf7dac9621ef58` to the POC runtime correction that
exposes the already-reviewed Chat authorized-result discovery contract through
the Node streaming and non-streaming endpoints.

The Product separates three bounded concerns:

- answer evidence remains a small, provider-resolved context;
- authorized discovery retains a wider ranked candidate window without
  inventing an exact total or cursor;
- the response hands the canonical Catalog query and field scope to the UI so
  the user can explore all authorized filtered pages through the existing
  Catalog API.

Natural-language discovery hands off an empty Catalog query over the current
authorized Table inventory. Identifier-shaped discovery hands off the exact
bounded identifier and `TABLE` field scope. GENERAL, GRAPH, and Knowledge Asset
routes do not invent a DataHub Catalog discovery result. Request timing reports
routing, retrieval, optional reranking, composition, and total latency without
persisting provider timing or discovery payloads into Chat history.

CH-01, CH-02, and CH-03 remain `IN_PROGRESS` at this Evidence checkpoint.
They may close only after the exact Product is deployed to the preserved TEST
accepted state and the first and next authorized Catalog pages plus measured
stage timings are verified end to end.

Quality, Airflow, and MCP safety holds remain `NEEDS_DECISION` or
`BLOCKED_EXTERNAL`; this release does not represent those holds as completed.

## Authorization and data contract

- Discovery is derived only after the existing request principal filters
  DataHub candidates.
- The Product never introduces an anonymous or broader-credential retry.
- `total` is `null`, `total_exact` is `false`, and `next_cursor` is `null` at
  the Chat boundary; the canonical Catalog API owns exact pagination.
- No fixed Dataset, GlossaryTerm, business name, provider count, host, or
  environment identity is used by runtime logic.
- The change performs no DataHub metadata mutation and does not alter K9, MCL,
  migration, classification, or release safety contracts.

## Local verification

All commands ran from the clean Product source before the image build:

- full Node POC server suite: `201/201` PASS;
- full UI Vitest suite: `93` files, `731/731` PASS;
- TypeScript typecheck: PASS;
- full ESLint: PASS;
- POC build: PASS;
- application build: PASS;
- static/source integrity and accepted migration checksums: PASS;
- `git diff --check`: PASS.

The existing bundle-size advisory remains informational and unchanged in
severity. No Product dependency or lockfile changed.

## Exact Product artifact

The clean Product was built once for `linux/amd64`; the export command did not
build, pull, or load another image.

| Identity | Exact value |
| --- | --- |
| Product | `567da6ba6e11f5b72126dffa3ccf7dac9621ef58` |
| image | `datariver-poc:567da6ba6e11f5b72126dffa3ccf7dac9621ef58` |
| child manifest / image ID | `sha256:f6de135e4bdbeea3cf92d566cab37964fe9684203a889fd2b31e8e3676abb39e` |
| config digest | `sha256:4d8e61969e6fd8d33bbb0966c627473d8e7d14da94b8abdd9341a77ff79bad6d` |
| archive SHA-256 | `2c8246d5bab1cb52c956eba95f11c325dcf855a79f901d7f022dee79d6f13df6` |
| platform | `linux/amd64` |
| OCI revision | exact Product SHA |

The previously published Wave C and cumulative archives are historical
intermediate artifacts and are not reused, retagged, or promoted for this
Product.

## Runtime boundary

- Existing TEST accepted state: preserved.
- TEST deployment of this exact Product: PENDING at this Evidence checkpoint.
- Actual PREP: NOT EXECUTED.
- Actual OPS: NOT EXECUTED.
- `origin/main`: frozen.
- user metadata modified: NO.

The next Handoff pins only the artifact identities above, pushes the exact
Handoff to `origin/dev`, and performs the canonical same-command TEST
accepted-state redeploy with no reset, resecret, rebuild, or mutable pull.
