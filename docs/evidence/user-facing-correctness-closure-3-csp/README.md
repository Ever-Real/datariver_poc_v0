# USER-FACING-CORRECTNESS-CLOSURE-3 strict-CSP evidence

Recorded: 2026-08-30 (Asia/Seoul)  
Starting Product: `f47521cd2a58639492bb6e5e76ea39d27d6a9ba6`  
Current Product: `d343e14d6a5159151586e5d3e20655c88b8920df`

## Recovery state preserved

The starting Product remains a TEST runtime partial result. Its Web container was healthy with
restart count `0` and user `1000:1000`, while the canonical deploy stopped at
`K9_INITIAL_REFRESH / PREP_SMOKE_SEMANTIC_INDEX_NOT_READY`. The previously accepted Product,
accepted marker, graph last-known-good generation and three state-service volumes remain intact.
No reset, resecret, retry expansion, graph rebuild, direct index mutation or user DataHub metadata
mutation was performed.

## Strict-CSP correction

- General nginx now emits exact `style-src 'self'` without `unsafe-inline`.
- FlowCanvas and Knowledge Studio GraphBuilder no longer own React style props or CSSOM writes for
  wrapper height, node/edge presentation, handles, tree indentation, group dimensions, connection
  lines, quick editor scaling or edge-label placement.
- Finite presentation moved to external CSS; ReactFlow typed `width`/`height`, NodeToolbar and
  EdgeToolbar contracts retain dynamic geometry.
- Pinned `@xyflow/react` 12.11.2 still emits client-side CSSOM geometry for viewport, nodes,
  toolbars, markers, MiniMap and Background. Published 12.11.5 has the same boundary and no nonce
  or CSP option. The exercised client-rendered Product path remains functional under strict CSP.

## Verification

- Focused frontend: `36/36` passed, including `1`, `5`, `50` and `200` node fixtures.
- Full frontend: `95` files, `799/799` passed.
- Focused Python nginx/static: `6/6` passed.
- TypeScript, touched zero-warning ESLint, Ruff, static verification, diff check and production
  build: PASS.
- Strict-CSP GraphBuilder browser probe: CSP violations `0`, console messages `0`, injected style
  elements `0`; nodes, EdgeToolbar, Controls, MiniMap, quick editor and computed viewport transform
  remained functional.
- Current direct TEST public-login asset evidence remains console errors `0`, warnings `0`. The
  candidate was not claimed as authenticated TEST browser accepted.
- Runtime business-keyword/URN special cases introduced: `0`.
- Authorization widening, CSP relaxation, reset/resecret and user DataHub metadata mutation: NONE.

## Exact build-once artifact

- image: `datariver-poc:d343e14d6a5159151586e5d3e20655c88b8920df`
- platform: `linux/amd64`
- archive: `datariver-poc-d343e14d6a5159151586e5d3e20655c88b8920df-linux-amd64.tar`
- archive SHA-256: `6fe5043e5c837b9c19a421e57750deec7cbcdf7260b4d4a6a7d069cfecdd00e4`
- child manifest: `sha256:5adf95d4313a3115b0cab351d5ca41095f7598be9fff75b34df6ca2e16c4b91c`
- config: `sha256:b89e54de5af4b17be26d1c5c2c9cec7c186194f64cfee815256998868b9ada23`
- OCI revision: `d343e14d6a5159151586e5d3e20655c88b8920df`
- runtime user/command: `node` / `node poc-server.mjs`

The artifact was built once through `scripts/prep39083_product_artifact.py` from an exact clean
temporary `dev` checkout of the immutable Product. The existing dirty canonical `dev` worktree and
all quarantined worktrees were preserved. Deployment remains archive load plus the canonical
`--no-build` command.

## Remaining acceptance boundary

The unchanged TEST semantic-index generation mismatch remains a typed external runtime blocker, so
the same failing deploy gate is not repeated without a K9 correction. Authenticated target-browser
acceptance remains blocked at the credential-entry boundary; public target assets and the local
strict-CSP authenticated fixture are not overstated as that acceptance.

Actual PREP and Actual OPS were not executed. `origin/main` remains unchanged.
