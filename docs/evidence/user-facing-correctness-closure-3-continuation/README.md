# USER-FACING-CORRECTNESS-CLOSURE-3 continuation evidence

Recorded: 2026-08-30 (Asia/Seoul)  
Previous TEST Product: `9fb8aba7b0b23a63a803cf6d5fcbca1852c3bf01`  
Previous TEST Evidence: `65f07fc602dd4304341b3b7d9d08c4b873be0d4e`  
Previous TEST Handoff: `b61f0cc074462024484b5d848ab847962306c5db`  
Current Product: `f47521cd2a58639492bb6e5e76ea39d27d6a9ba6`

## Recovery boundary

The previous exact Product first deployment remains accepted at `6/6`. Its same-command rerun is
recorded separately as failed at `K9_INITIAL_REFRESH / PREP_SMOKE_SEMANTIC_INDEX_NOT_READY`: both
canonical graph projections and their last-known-good state remained ready, while the shared
semantic index stayed pending until the existing bounded timeout. No graph reset, resecret, volume
deletion, retry expansion or retrospective change to the first accepted result was performed.

## Incremental Product result

- Home Total Datasets and schema metadata registration lists use bounded vertical scrolling. Schema
  identity typography is reduced without truncating the server-provided authorized rows.
- Local-human creation protects a dirty form with an explicit discard confirmation while retaining
  the shared application-dialog Escape/backdrop contract.
- Chat keyword discovery consumes canonical real cursors to the exact authorized total, persists a
  bounded server-owned discovery descriptor, revalidates current authorization when history is
  read, accepts Unicode exact identifiers, and falls back when the Clipboard API rejects. The
  Product-owned PostgreSQL catalog advances immutably from V4 to V5 through ordered migration 007.
- The K10 portability simulator follows the current K9 batched node/edge write and typed
  classification-failure contracts. Product K9 graph, semantic-index and accepted-state code was
  not changed by that correction.
- Runtime inline presentation was removed from the progress, Quality gauge/legend, Governance
  status columns, controlled-vocabulary portal, Knowledge registry drawer and Chat composer paths.
  The POC Node server retains strict `style-src 'self'`; Cytoscape remains exact-source patched and
  CSP was not relaxed.

## Verification

- Full Node suite: `394` total, `381` passed, `13` explicitly environment-gated skipped, `0` failed.
- Full frontend Vitest: `95` files, `792/792` passed.
- Focused Chat: `36/36`; provider: `33/33`; state/schema: `39/39`.
- Focused Governance: `35/35`; Registration: `30/30`; Knowledge registry: `3/3`.
- TypeScript, touched zero-warning ESLint, diff checks and POC production build: PASS.
- Runtime business-keyword/URN special cases introduced: `0`.
- Authorization widening, CSP relaxation, reset/resecret and user DataHub metadata mutation: `NONE`.

## Exact build-once artifact

- image: `datariver-poc:f47521cd2a58639492bb6e5e76ea39d27d6a9ba6`
- platform: `linux/amd64`
- archive: `datariver-poc-f47521cd2a58639492bb6e5e76ea39d27d6a9ba6-linux-amd64.tar`
- archive SHA-256: `820910c210f0f551cdb08d32240eb9d37dbe9bf476f071c33fac808020685b08`
- child manifest: `sha256:035fa3a98b7ab2aec338ba1f365b0baf1ba3f911c4677b61141fcc920731f88b`
- config: `sha256:8e06de6804f4a170d244b6afd2df1f8e56391cc11c83c81f64da204f06ace790`
- OCI revision: `f47521cd2a58639492bb6e5e76ea39d27d6a9ba6`
- runtime user/command: `node` / `node poc-server.mjs`

The artifact was built once through `scripts/prep39083_product_artifact.py` from an exact clean
`origin/dev` checkout. The existing dirty `dev` worktree was preserved; no file was stashed,
overwritten or discarded. Deployment remains archive load plus the canonical `--no-build` command.

## Remaining acceptance boundary

This Evidence is local/artifact evidence and does not claim that Product `f47521cd...` is TEST or
browser accepted. Exact archive checksum/doctor/deploy, first `6/6`, same-command rerun and current
asset browser acceptance remain required. Search/Chat parity must be exercised under the same
principal with non-zero English, Korean, exact-name, description and term/tag fixtures. The
ReactFlow-based FlowCanvas/GraphBuilder editor boundary and the separate nginx template's
`unsafe-inline` policy remain a focused CSP backlog; the tested POC Cytoscape lineage path is not
reported as failed by that separate boundary.

Actual PREP and Actual OPS were not executed. `origin/main` remains unchanged.
