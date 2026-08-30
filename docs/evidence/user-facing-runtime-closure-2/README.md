# USER-FACING-RUNTIME-CLOSURE-2 Evidence

Date: 2026-08-30 KST
Product: `8e7d9f3fe3a620c4a7b301ff96b05939e4b57798`
Starting TEST Handoff: `5d6491554512b002a40f7bb5642dcf64695c9898`
Actual PREP: not executed
Actual OPS: not executed

## Bounded Product scope

This Product preserves the previously accepted timeout and Chat-router contracts and adds only the
requested user-facing closure surfaces:

- System creation confirmation/error visibility and concise server-owned immutable code UX;
- authorized Change History event visibility without guessing a missing Table-to-System mapping;
- page-bounded Glossary assignment counts and Home Dataset schema drill-down;
- Governance editor close protection, canonical italic retention, CSP-safe table editing and readable names;
- cursor-append Resource Tree virtualization, bounded detail-history restore, and owner-bound Catalog CSV/XLSX export.

Unmapped Change History events are selected only from the principal's exact current Table authority.
They carry `UNMAPPED`, no System identity, no assignee, no CR link actions, and no authorized linked CR.
System mapping remains exact Dataset URN to canonical System UUID; fuzzy matching was not added.

No GX provider or infrastructure was invented. The repository has no reviewed canonical GX runtime
provider for this release, so GX runtime acceptance remains an explicit product/environment gap.

## Local verification

- focused frontend integration: `140/140 PASS`;
- Node authorization/server/export/glossary/change-history bundle: `70/70 PASS`;
- backend Governance/export/S3: `98/98 PASS`;
- TypeScript typecheck, ESLint, POC build and application build: PASS;
- static/source and accepted migration checksum integrity: PASS;
- changed-diff runtime target-data special cases: `0` (generic synthetic test identities only);
- `git diff --check`: PASS.

The historical broad migration and K9 audits were not repeated. No migration source changed.

## TEST accepted-state and browser evidence

The predecessor Product `e2df77ba03f519785963cabe46ba997dd115c7ad` was deployed from its exact
archive into the retained TEST accepted state and passed the canonical 6/6 smoke twice: the first
deploy in 579 seconds and the same-command rerun in 201 seconds. The running Web container was
healthy, had restart count zero, ran as `1000:1000`, and used the exact pinned image without a
build, reset, resecret or user metadata mutation.

After a forced browser asset reload, TEST verified the Glossary initial page and numeric
table/column assignment counts, Home/Glossary total reconciliation at 34 authorized current terms,
and real CSV/XLSX export responses with correct content types and bounded filenames. Expanding a
schema in the Home Total Datasets modal then reproduced a current-Product render failure:
`catalog_schema_metrics` omitted `tagged_asset_count` and `term_asset_count`, while the typed UI
contract required both values. The new Product computes both exact counts from the already
authorized inventory; it does not add provider requests, default missing data to zero in the UI, or
weaken the modal error boundary.

The focused provider/server suite (`29/29`), TypeScript typecheck, ESLint, production build and
`git diff --check` pass for this bounded correction. A fresh exact-Product TEST redeploy and modal
drill-down acceptance remain required before this successor is represented as TEST accepted.

## Exact Product artifact

The clean Product was built once for `linux/amd64` and exported without rebuilding:

- image: `datariver-poc:8e7d9f3fe3a620c4a7b301ff96b05939e4b57798`;
- OCI revision: `8e7d9f3fe3a620c4a7b301ff96b05939e4b57798`;
- archive SHA-256: `cd4e755cfdfc92c0251ef313faa0d1ac4104435ac7220706459c5aba4ac4ce32`;
- child manifest: `sha256:243a164890fd8978babf806a09e5e3c6d07968e0a908ea6a24caa92ddb221888`;
- config: `sha256:8be54f18accbfdf69926e9b34c51690021373bf491d227c920d1c99b2a788d14`;
- runtime user: `node` (`1000:1000` in the PREP Compose contract).

The archive is ignored and transported separately. TEST must verify checksum, manifest, config,
platform and revision before `docker load`, and start only through Compose `--no-build` with no pull
or rebuild fallback.

## Runtime gates still required

The predecessor TEST Product `e2df77ba03f519785963cabe46ba997dd115c7ad` remains the last accepted
runtime until this Product completes accepted-state deploy, 6/6 smoke, same-command rerun and the
bounded browser/API matrix. Source-level results are not represented as TEST acceptance.

TEST validation must preserve existing volumes, secrets, identities and user metadata. Actual PREP
and Actual OPS remain outside this work.
