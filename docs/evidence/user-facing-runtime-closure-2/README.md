# USER-FACING-RUNTIME-CLOSURE-2 Evidence

Date: 2026-08-30 KST
Product: `32377cf3b8b5cdd97cdaaa6833495f2f445b46a2`
Starting TEST Handoff: `3790852f6916dc4643e837a86808230d26311c43`
Actual PREP: not executed
Actual OPS: not executed

## Bounded Product scope

This descendant preserves the TEST-accepted timeout, Chat-router, Home, Glossary, Search, Change
Detection and exact export contracts.  Interruption recovery added only two bounded Product deltas:

- the Resource Tree endpoint accepts its existing 200-item request while ordinary Catalog pages
  remain capped at 100;
- the POC Governance detail adapter projects document-scoped display names from the existing
  workspace membership source instead of forcing the UI to fall back to UUIDs.

Unmapped Change History events are selected only from the principal's exact current Table authority.
They carry `UNMAPPED`, no System identity, no assignee, no CR link actions, and no authorized linked CR.
System mapping remains exact Dataset URN to canonical System UUID; fuzzy matching was not added.

No GX provider or infrastructure was invented. The repository has no reviewed canonical GX runtime
provider for this release, so GX runtime acceptance remains an explicit product/environment gap.

## Local verification

- Resource Tree/DataHub scale: `6/6 PASS`; provider boundary: `29/29 PASS`;
- Catalog workspace: `35/35 PASS`, including 10,000+ cursor-append rows with bounded DOM windowing;
- Governance/POC adapter focused: `57/57 PASS`; editor markup/table subset: `44/44 PASS`;
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

The predecessor Product `8e7d9f3fe3a620c4a7b301ff96b05939e4b57798` is the last TEST-accepted
runtime. Its exact archive passed the canonical 6/6 smoke on the first retained-state deploy in
559 seconds and on the same-command rerun in 209 seconds. Web was healthy with restart count zero,
ran as `1000:1000`, and used the exact pinned image without a build, reset, resecret or user
metadata mutation.

The retained browser session verified Home Dataset drill-down/back with the modal still open,
Glossary `34/34` with numeric table/column assignment counts and no timeout, Search base detail with
14 columns and no timeout, and 25 authorized Change Detection events without an Admin CTA.
Governance interruption recovery additionally verified that Escape and outside clicks do not close
a dirty authoring modal, Cancel uses the unsaved-change confirmation, and the existing table editor
exposes bounded row/column operations plus a CSP-safe controlled cell color. No TEST document was
persisted because supported cleanup was not proven.

The Resource Tree correction and Governance display-name correction are not inherited from that
runtime. They require one new exact-Product accepted-state deploy, 6/6 rerun and bounded browser
acceptance before this successor is represented as TEST accepted.

## Exact Product artifact

The clean Product was built once for `linux/amd64` and exported without rebuilding:

- image: `datariver-poc:32377cf3b8b5cdd97cdaaa6833495f2f445b46a2`;
- OCI revision: `32377cf3b8b5cdd97cdaaa6833495f2f445b46a2`;
- archive SHA-256: `74d05504bd80708946510b12dcf3b659de97e7b6cb53290d3af76dee90be0768`;
- child manifest: `sha256:0d9b55b9ce3553c69183f097674d535df0bdfcf93cfa72f97e4121d1e5fe089d`;
- config: `sha256:924ddf8009d7237460e34d95130037a9a1d96f19bd78020b2ffa68445a9fd251`;
- runtime user: `node` (`1000:1000` in the PREP Compose contract).

The archive is ignored and transported separately. TEST must verify checksum, manifest, config,
platform and revision before `docker load`, and start only through Compose `--no-build` with no pull
or rebuild fallback.

## Runtime gates still required

The predecessor TEST Product `8e7d9f3fe3a620c4a7b301ff96b05939e4b57798` remains the last accepted
runtime until this Product completes accepted-state deploy, 6/6 smoke, same-command rerun and the
bounded Resource Tree/Governance browser matrix. Source-level results are not represented as TEST
acceptance.

TEST validation must preserve existing volumes, secrets, identities and user metadata. Actual PREP
and Actual OPS remain outside this work.
