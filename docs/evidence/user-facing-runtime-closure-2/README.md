# USER-FACING-RUNTIME-CLOSURE-2 Evidence

Date: 2026-08-30 KST
Product: `888a484c2d03dc9221f63e2a623c301fa0e69c1b`
Starting TEST Handoff: `bf57134acf79c7ce26aebb52f942fd0fdb2f512b`
Actual PREP: not executed
Actual OPS: not executed

## Bounded Product scope

This descendant preserves the TEST-accepted timeout, Chat-router, Home, Glossary, Search, Change
Detection and exact export contracts. Interruption recovery added only three bounded Product deltas:

- the Resource Tree endpoint accepts its existing 200-item request while ordinary Catalog pages
  remain capped at 100;
- the POC Governance detail adapter projects document-scoped display names from the existing
  workspace membership source instead of forcing the UI to fall back to UUIDs;
- a referenced legacy POC document actor retains its bounded presentation label after live state
  hydration replaces the default membership list, while a real same-subject membership still wins.

Unmapped Change History events are selected only from the principal's exact current Table authority.
They carry `UNMAPPED`, no System identity, no assignee, no CR link actions, and no authorized linked CR.
System mapping remains exact Dataset URN to canonical System UUID; fuzzy matching was not added.

No GX provider or infrastructure was invented. The repository has no reviewed canonical GX runtime
provider for this release, so GX runtime acceptance remains an explicit product/environment gap.

## Local verification

- Resource Tree/DataHub scale: `6/6 PASS`; provider boundary: `29/29 PASS`;
- Catalog workspace: `35/35 PASS`, including 10,000+ cursor-append rows with bounded DOM windowing;
- Governance/POC adapter focused: `57/57 PASS`; editor markup/table subset: `44/44 PASS`;
- final hydrated legacy-actor regression: `39/39 PASS`;
- POC server: `221 PASS`, `10` explicit isolated-PostgreSQL skips;
- TypeScript typecheck, ESLint, POC build and application build: PASS;
- static/source and accepted migration checksum integrity: PASS;
- changed-diff runtime target-data special cases: `0`;
- `git diff --check`: PASS.

The complete frontend run passed `750/755`.  Its five failures are unchanged `PocApp` request-list
assertions that do not include the already-shipped Catalog export-capability request. Neither the
tested `PocApp` source nor those assertions changed between the last TEST-accepted Product and this
Product, so the failures are recorded as pre-existing expectation debt rather than hidden or
rewritten in this bounded closure. Focused changed-surface tests and TEST runtime remain release
gates. The historical broad migration and K9 audits were not repeated; no migration source changed.

## TEST accepted-state and browser evidence

The predecessor Product `32377cf3b8b5cdd97cdaaa6833495f2f445b46a2` is the last TEST-accepted
runtime. Its exact archive passed the canonical 6/6 smoke on the first retained-state deploy in
556 seconds and on the same-command rerun in 206 seconds. Web was healthy with restart count zero,
ran as `1000:1000`, and used the exact pinned image without a build, reset, resecret or user
metadata mutation.

The retained browser session verified Home Dataset drill-down/back with the modal still open,
Glossary `34/34` with numeric table/column assignment counts and no timeout, Search base detail with
14 columns and no timeout, and 25 authorized Change Detection events without an Admin CTA.
Governance interruption recovery additionally verified that Escape and outside clicks do not close
a dirty authoring modal, Cancel uses the unsaved-change confirmation, and the existing table editor
exposes bounded row/column operations plus a CSP-safe controlled cell color. No TEST document was
persisted because supported cleanup was not proven.

That runtime verified Resource Tree counts `206 -> 406 -> 606` (six hierarchy nodes plus 200-item
pages), distinct loaded identities, continued cursor availability, no Tree first/previous/next
controls and zero browser console errors. It also proved that the initial Governance display-name
projection remained incomplete for legacy POC-authored documents after live membership hydration;
the final Product adds only the bounded correction described above. This final successor still
requires one exact-Product accepted-state deploy, 6/6 rerun and Governance browser acceptance before
it is represented as TEST accepted.

## Exact Product artifact

The clean Product was built once for `linux/amd64` and exported without rebuilding:

- image: `datariver-poc:888a484c2d03dc9221f63e2a623c301fa0e69c1b`;
- OCI revision: `888a484c2d03dc9221f63e2a623c301fa0e69c1b`;
- archive SHA-256: `59f60837c3f90c7f60c3b7ae9db6ce93df3e16e917a604732424ed2947257d6d`;
- child manifest: `sha256:d1550a15782d9c0dc2615f368c1876c85e35243ec6d18b773b1dfc595d2be794`;
- config: `sha256:2228da4bcd9c2b00f374bacb72350c06a5ab400fb90e2450b0331f6be66fe822`;
- runtime user: `node` (`1000:1000` in the PREP Compose contract).

The archive is ignored and transported separately. TEST must verify checksum, manifest, config,
platform and revision before `docker load`, and start only through Compose `--no-build` with no pull
or rebuild fallback.

## Runtime gates still required

The predecessor TEST Product `32377cf3b8b5cdd97cdaaa6833495f2f445b46a2` remains the last accepted
runtime until this Product completes accepted-state deploy, 6/6 smoke, same-command rerun and the
bounded Resource Tree/Governance browser matrix. Source-level results are not represented as TEST
acceptance.

TEST validation must preserve existing volumes, secrets, identities and user metadata. Actual PREP
and Actual OPS remain outside this work.
