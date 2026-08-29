# Wave C/D contract-closure evidence

## Boundary

This local checkpoint records cumulative source Product
`72fde0af0601a04a819eaffbd891e1f1f1788471` after the published Wave C
Handoff `f9c9d7595c70b70d41728e01ce66cc0406e92f28`.

It is not a final release Handoff. TEST PC transport is unavailable, no fresh
cumulative OCI has been built, `origin/main` remains frozen, and Actual PREP
and Actual OPS were not executed.

The previous Wave C archive `dec34d0d...` is immutable evidence for Product
`1ad090d084b34906438e281ee208f9ec49d9a95f` only. Current source-check rejects
using that release identity for this descendant because runtime inputs changed.
It is therefore an intermediate artifact and is prohibited as the final OCI.

## Chat result exploration

The cumulative Product keeps LLM answer context, visible evidence, and full
Catalog candidate exploration as separate bounds:

- VECTOR discovery returns the exact Catalog query scope that was used before
  semantic ranking. Natural-language retrieval carries an empty query across
  all Catalog fields; an identifier anchor carries that exact anchor and the
  TABLE field only.
- GENERAL reuses the exact bounded lexical term sent to Catalog. GRAPH produces
  no Catalog handoff.
- The Chat response does not invent an exact total or cursor and does not rerun
  or persist another LLM answer for pagination.
- The UI opens the canonical Catalog with the exact query and validated search
  fields. Catalog performs current-principal authorization on each cursor page.
- Copy explicitly describes a Catalog candidate scope, not pagination of the
  semantic rank or evidence badges.

Local verification covers empty-query full-inventory handoff, TABLE-scoped
identifier handoff, invalid/duplicate field rejection, and the Catalog request
scope. `CH-01`, `CH-02`, and `CH-03` remain `IN_PROGRESS` until TEST PC proves
first-page and next-page exploration and records target route/search/vector/
rerank/provider/first-token/total timings.

## Quality disposition

The safe bounded work is preserved:

- authorized metadata-scope preview;
- bounded target counts;
- replay identity for proposal retry;
- no direct DataHub/GX backing-store mutation.

`DQ-01` and `DQ-02` remain `NEEDS_DECISION`, not complete. The canonical
DataHub projection does not expose an authoritative nullability field, so native
type strings are not treated as nullability. The Product also has no approved
durable recommendation/provenance/confidence/approval aggregate. Existing
Knowledge, Governance, and registration aggregates are not repurposed.

## Airflow disposition

The Product exposes a reviewed read-only five-DAG inventory under
`admin.manage`. Arbitrary/non-allowlisted DAGs remain rejected. The manual
trigger endpoint now returns sanitized
`AIRFLOW_TRIGGER_SAFETY_HOLD` before request-body parsing or provider contact,
because the existing path had no durable idempotency receipt, audit retention,
or lost-response reconciliation.

`AF-02`, `AF-03`, and `AF-04` remain `NEEDS_DECISION`. No browser-writable
secret/auth-mode ownership contract and no exact System-to-DAG association
aggregate are approved. The separate registration-owned execution path is
unchanged.

## MCP disposition

The accepted fixed service-subject, fixed Workspace, read-only MCP boundary is
unchanged. Exact token checking, current canonical authorization/classification,
workspace-override rejection, bounded provider failure classification, and
token non-leak tests remain verified.

`MP-04` is `NEEDS_DECISION`: there is no approved human delegation transport,
tool-to-capability policy, or immutable per-call audit aggregate. `MP-06` is
`BLOCKED_EXTERNAL` until that decision and exact TEST runtime acceptance. The
generic mutable Node state store and unrelated Chat/Sharing/Knowledge receipts
are not reused as fake MCP audit evidence.

## Integrated verification

- Chat backend focused: `90/90` PASS.
- Chat/Catalog/Admin focused UI: `78/78` PASS.
- full Node Product server: `200/200` PASS.
- full UI Vitest: `93` files, `731/731` PASS.
- PREP smoke contract: `34/34` PASS.
- release/deploy/handoff/migration integrity: `148/148` PASS.
- prior Quality focused backend/UI: `97/97` and `16/16` PASS.
- prior integrated Airflow Node/UI: `79/79` and `33/33` PASS.
- TypeScript typecheck and full ESLint: PASS.
- changed-source Ruff and strict mypy: PASS.
- application build and POC build: PASS, retaining only the existing chunk-size
  advisory.
- static/source integrity and `git diff --check`: PASS.

The first Control Plane focused invocation used repository-relative paths from
the frontend subdirectory and discovered no tests. It was an invocation-path
error, not a Product failure; the corrected commands produced the PASS results
above.

## Release and runtime state

- final cumulative OCI: NOT BUILT;
- final Product/Evidence/Handoff: NOT RELEASED;
- `origin/dev`: remains the last published intermediate Handoff `f9c9d75`;
- `origin/main`: `17f32a52de79077c433bf0beaabac81a48e46062`, unchanged;
- TEST PC: `BLOCKED_EXTERNAL`; prior accepted state preserved;
- user DataHub metadata modified: NO;
- Actual PREP: NOT EXECUTED;
- Actual OPS: NOT EXECUTED.

When TEST transport recovers, source closure is rechecked first. A fresh exact
linux/amd64 OCI is built from the then-current cumulative Product, exported and
pinned by checksum/manifest/config/revision, and deployed through the canonical
accepted-state `./scripts/prep39083 deploy` path with no build, reset, or
resecret. The intermediate Wave C OCI is never reused.
