# User-facing runtime backlog closure evidence

Date: 2026-08-30 KST  
Product: `86f1d0a1e99f188bf3bde261038429b93f05ec75`  
Starting Handoff: `e17b5617cc1ededc87a46247d93a6b6ddc24d924`  
Actual PREP: not executed  
Actual OPS: not executed

## Bounded Product closure

This Product closes one cumulative user-facing bundle without changing the accepted-state,
PostgreSQL-owned-schema, K9 consistency, artifact-only deployment, secret, Origin, or runtime-user
contracts.

- Home now uses four compact canonical summary cards and four bounded analytics cards. Total
  Datasets opens the authorized Dataset search and Governance Center is not duplicated on Home.
  Where no approved historical read model exists, the UI reports
  `HISTORICAL_DATASET_COUNT_SOURCE_UNAVAILABLE` and
  `CHANGE_TO_CR_7_DAY_SOURCE_UNAVAILABLE`; it does not invent a trend or ratio.
- Chat preserves the existing router, recall, and authorization boundary. The server-owned Catalog
  handoff is visible independently of the bounded evidence preview. A natural-language ASCII
  keyword becomes the Catalog TABLE query only when it matches a canonical authorized Dataset
  evidence identity. Identifier-shaped but unrelated tokens cannot bypass that evidence fence.
- System creation accepts name and description only. The server creates immutable collision-safe
  identity/code values behind `admin.manage`, Origin, current-admin, CAS, and idempotency checks.
  CR creation continues to require an active exact Table-to-System mapping and now preserves the
  typed intake fields. Its current Table authority accepts exactly one supported classification
  tag and rejects missing, duplicate, invalid, mismatched, or impossible-calendar input.
- Quality/GX remains fail-closed without a canonical control plane. Airflow presence no longer
  fabricates manual-run availability, REGEX execution, or queued runs.
- Profile no longer exposes invented editable identity fields or a no-op save control. The current
  IdP has no approved self-service identity-write contract; that policy decision remains explicit.
- Governance retains the existing TipTap/ProseMirror OSS editor and sanitizer. The editor workspace
  is more compact, published metadata uses the requested primary layout, and approval/relationship
  facts remain available as secondary metadata. No CSP relaxation or arbitrary HTML/style path was
  introduced.
- CSV and XLSX buttons now start the existing complete authorized server export and automatically
  consume its safe download URL when the artifact is ready; no second download action is required.
- Site Management stores at most five ordered custom links in the Product-owned branding state.
  The server owns badge identities, accepts the legacy state shape, enforces CAS/idempotency and
  safe raster assets, rejects unsafe/credential-bearing URLs and foreign identities, and never
  fetches the configured URL.

No runtime business Dataset, GlossaryTerm, System, schema, host, platformInstance, or fixed result
count was added. New `wafer` and concrete Dataset URN references are provider test fixtures only.
Runtime target-data hardcoding count for this delta is zero. No migration or user DataHub metadata
mutation is part of this Product.

## Verification

- focused frontend integration: `172/172 PASS`;
- complete frontend Vitest: `759/759 PASS`;
- focused authorization/server: `69/69 PASS`;
- complete bounded POC server suite: `229 PASS`, `10` unchanged real-PostgreSQL environment-gated
  skips, `0` failures;
- final provider/Chat suite after evidence-bound correction: `31/31 PASS`;
- site branding backend/frontend: `12/12` and `24/24 PASS`;
- application build and POC build: PASS;
- TypeScript, ESLint, Node syntax, and diff checks: PASS;
- static/source integrity including migration checksums and exact-artifact contract: PASS;
- one independent cumulative review found three fail-closed blockers; the bounded corrections and
  one focused re-audit closed classification/date issues. Its remaining identifier bypass was then
  corrected and Control Plane verified with the negative provider test.

Browser acceptance is not claimed because no controllable TEST browser surface was connected at
this checkpoint. Profile identity editing, CR revision persistence, and a real GX control plane are
not fabricated; they remain typed policy/external gaps. Existing Resource Tree and stateful
Previous contracts were not reopened without new runtime evidence.

## Exact Product artifact

The clean Product image was built for `linux/amd64` and exported through the approved archive
contract:

- image: `datariver-poc:86f1d0a1e99f188bf3bde261038429b93f05ec75`;
- archive SHA-256: `7a52684cd77886dc09998534ff6e32ab07b38787bd9f7abc7836511602a5f922`;
- child manifest: `sha256:40ac298bc6013131a888b87d64a54ce0d6eefd54c463166c0139889ca046bc16`;
- config: `sha256:cebc06e588bf09bd99991db852916d63381ded4b7f87e699f0bc28966582b54b`;
- platform: `linux/amd64`;
- OCI revision: `86f1d0a1e99f188bf3bde261038429b93f05ec75`.

An initial non-canonical frontend-only image was exported during release preparation. TEST doctor
rejected it before service start because it could not execute the required Product Node preflight.
That archive was superseded and was never deployed. The exact image recorded above was then built
once from the tracked canonical `deploy/poc/Dockerfile.example`; TEST/PREP deployment never builds
or pulls it.

## Runtime gate

Product `1adfe1ced2c9311bcbb880bfac400a1edf8d9178` remains the last TEST-accepted runtime until this
new exact descendant completes accepted-state deployment, 6/6 smoke, same-command rerun, and the
available API/browser checks. Existing volumes, secrets, identities, and user metadata must be
preserved. Actual PREP, Actual OPS, and `origin/main` remain outside this closure.
