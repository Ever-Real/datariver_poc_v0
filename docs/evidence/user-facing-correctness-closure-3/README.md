# USER-FACING-CORRECTNESS-CLOSURE-3 evidence

Recorded: 2026-08-30 (Asia/Seoul)  
Starting Handoff: `656f02499e8d922635edfa6e6217a76020fb5bad`  
Starting TEST Product: `86f1d0a1e99f188bf3bde261038429b93f05ec75`  
Product: `9fb8aba7b0b23a63a803cf6d5fcbca1852c3bf01`

## Bounded Product result

- CR creation has explicit-only dismissal, governed existing/new column proposals, exact current
  classification binding, and current-schema membership checks that fail closed even when the
  provider exposes no fields.
- Local-human creation normalizes duplicate email identity, accepts passwords from eight Unicode
  characters without truncation, and atomically records a secret-free administrator/subject audit
  receipt with the credential/access/core transaction.
- The Product-owned PostgreSQL contract advances from V3 to V4 without reset; fresh V4, exact known
  ancestry and exact V3-to-V4 convergence are accepted, while missing, partial, copied, newer and
  fingerprint-mismatched owned state stop before mutation. Non-owned database objects remain out of
  scope.
- Profile renders the authenticated principal's canonical email without inventing a second profile
  authority.
- Search detail/lineage Previous restores bounded UI snapshots instead of treating Previous as
  Close. True application dialogs require explicit actions; popovers and non-modal surfaces keep
  their existing semantics.
- Chat keyword discovery uses Unicode NFKC terms and the same canonical `catalog` feature scope as
  Search, with exact totals, real cursor pagination and a separate bounded semantic narrative. The
  answer prompt is told that bounded evidence is not the complete result. No business keyword has a
  Product runtime special case.
- Cytoscape 3.34.1 is exact-source patched at build time to remove both dynamic style-element
  injection and renderer inline-style writes. External Product CSS owns renderer presentation;
  version, source, entrypoint, digest and CSS mismatches fail closed. CSP was not relaxed.
- Governance keeps the pinned TipTap/ProseMirror editor, compact secondary panels, italic
  serialization/sanitization coverage and readable presentation. ADR 0115 records why Wiki.js is
  not embedded or substituted in this bounded closure.
- Home, GX capability presentation, duplicate Admin glossary navigation, site badges, Chat copy and
  real-workflow/progressive-reveal states retain their existing Product authorities and deny states.
  Progressive reveal is not represented as provider token streaming.
- The canonical Product artifact command builds only the Node Product Dockerfile for linux/amd64
  and rejects nginx-only, wrong entrypoint, wrong user, missing runtime files, mutable revision or
  platform mismatches before export.

## Independent review corrections

The single bounded independent review found three release blockers; all were corrected before the
Product checkpoint and the final focused re-review passed:

1. Chat Catalog discovery now intersects the canonical Search/Catalog feature cell rather than
   using the independent Chat cell for the full-result set.
2. an `EXISTING` CR column is never accepted merely because the current schema field set is empty;
3. the Cytoscape patch removes the library's dynamic `<style>` injection in addition to DOM style
   attribute writes.

## Verification

- Product Node/server/state/provider suite: `232 passed`, `12 environment-gated skipped`, `0 failed`
  (`244` total).
- Frontend Vitest: `94` files, `781 passed`, `0 failed`.
- Frontend TypeScript, zero-warning ESLint and POC production build: PASS.
- Cytoscape CSP exact-source gate: `7/7` PASS.
- PREP39083 release/deploy/migration suite: `146/146` PASS.
- Canonical Product artifact negative/positive gate: `7/7` PASS.
- Static source/integrity/checksum/document gate: PASS.
- `git diff --check`: PASS.
- Runtime target-business-data hardcoding introduced by Product files: `0`.
- Authorization widening, CSP relaxation, state reset/resecret and DataHub user metadata mutation:
  `NONE`.
- Final bounded independent review: PASS.

Real PostgreSQL mutation tests that require an explicitly acknowledged disposable PostgreSQL URL
remain environment-gated locally. Their matching in-memory/unit contracts passed; the owned-schema
migration and accepted-state behavior remain required TEST deployment gates.

## Exact build-once artifact

- image: `datariver-poc:9fb8aba7b0b23a63a803cf6d5fcbca1852c3bf01`
- transport: approved Docker archive
- platform: `linux/amd64`
- archive SHA-256: `ea06f12d6e3e37e367885ecceccdfaed3d67a9c6fd00877bde442f93d9e75575`
- child manifest: `sha256:274d72cb02516475d9afe5d609cde2f32e97009f7d9db8acf6937f12ffd1ff39`
- config: `sha256:1c8e3bcd335fef0a79b7f15ca005f3fee9b08361ae807c0ab3588ad8da453471`
- OCI revision: `9fb8aba7b0b23a63a803cf6d5fcbca1852c3bf01`
- runtime user/entrypoint: `node` / `node poc-server.mjs`

The prior accepted TEST artifact was not reused. The new artifact was built once from the clean
Product checkpoint with `scripts/prep39083_product_artifact.py`; target deployment is archive load
plus `--no-build`, with no pull/build fallback.

## Runtime boundary

This Evidence does not claim the new Product is TEST accepted. The previous Product
`86f1d0a1e99f188bf3bde261038429b93f05ec75` remains the last accepted TEST baseline until the exact
archive above completes existing-state deployment, V4 owned-schema integrity, 6/6 smoke,
same-command rerun and browser acceptance. Actual PREP and Actual OPS were not executed.
