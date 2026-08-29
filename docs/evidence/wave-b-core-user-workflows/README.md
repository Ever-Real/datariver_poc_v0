# Wave B core user-workflow evidence

## Scope and status

This checkpoint records the Wave B Product
`e131550b7fa441de85ded5b7b55083d77b8c643e`, based on the Wave A Handoff
`31663820f575e84e7060702144321abb44ec9ce4`.

Fifteen of the seventeen Wave B Epics are source/local verified:

- Home metadata coverage uses the current authorized inventory and distinguishes
  unavailable metrics from measured zero; Home also exposes canonical Change
  Request status groups without inventing domain states.
- Profile removes the four requested presentation-only fields. Self-service
  local password change verifies the current password, enforces the existing
  policy, rotates the credential and revokes the session. `AC-01` remains
  `NEEDS_DECISION` because the Product has no canonical immutable local-auth
  audit-event sink; credential `version`/`updated_at` is not represented as one.
- Admin adds bounded connection probes, server-owned collision-safe system
  codes, the canonical TanStack permission table, and managed site branding.
  Site branding is persisted in the existing Product state store, requires
  `admin.manage`, uses exact Origin and ETag/CAS, validates bounded PNG/JPEG/ICO
  bytes, rejects SVG/polyglots, and supports preview and restore without writing
  frontend source assets.
- Monitoring dashboard registration retains its persistent authorized backend
  contract while removing the affected inline frame sizing.
- Search adds bounded authorized CSV/XLSX exports, incremental Resource Tree
  paging, exact platform/database/schema/table click semantics, outside/Escape
  close with focus restoration, transient detail reset, bounded detail history,
  and stable Cytoscape geometry. No runtime business URN, Wafer fixture, or
  fixed result/node count was added.

`HM-03` remains `NEEDS_DECISION`: current canonical snapshots support the
requested current-state cards, but no historical read model exists for an honest
weekly data/metadata change trend. This checkpoint does not fabricate history.

## Security and architecture review

The Control Plane reviewed each integrated diff and retained backend
authorization as the enforcement boundary. The Site Management candidate also
received an independent bounded review. That review found and corrected two
issues before integration: idempotent replay could not bypass `If-Match`, and a
durable projection is revalidated before it is served. The final reviewer
disposition was `SAFE`, with its focused `20/20` suite passing.

The Product delta adds no dependency, migration, CSP relaxation, direct DataHub
DB write, provider credential exposure, PREP reset/resecret behavior, or OCI
fallback build. A diff scan found no new target-data URN or Wafer/semiconductor
runtime dependency. The new `poc-site-branding.mjs` runtime import is explicitly
copied by the Product Dockerfile and has a source-contract regression test.

## Verification

Product-focused results:

- full UI Vitest: `92` files, `700/700` PASS;
- full Node Product server: `195/195` PASS;
- canonical Catalog/search/navigation/export: `51/51` PASS;
- Site Management independent review: `20/20` PASS;
- PREP Handoff/runtime-copy focused contract: `17/17` PASS;
- TypeScript typecheck, ESLint, application build and POC build: PASS;
- Ruff lint and static/source verification: PASS;
- strict mypy over the 25 changed backend source files: PASS;
- `git diff --check`: PASS;
- exact OCI import of `/app/poc-site-branding.mjs`: PASS.

The complete backend pytest run produced `4077` PASS, `121` SKIP and `19`
failures. The failures are pre-existing baseline failures outside this Wave B
delta: stale migration-revision expectations, DEV host/preflight environment
tests, a documented-env example assertion, knowledge media/persistence tests,
and pilot-release baseline expectations. Full strict mypy likewise retains six
pre-existing errors in PREP test modules, and Ruff format retains five
pre-existing drift files. The changed-source mypy scope, Ruff lint, static gate,
and all Wave B focused suites pass. These baseline failures were not folded into
an unrelated feature change.

The frontend build retains only its existing large-chunk advisory and the UI
suite retains a non-failing jsdom canvas diagnostic. Local results are not
reported as browser or TEST PC acceptance.

## Exact Product artifact

The clean Product was built once for `linux/amd64` and exported without a
second build:

- image reference:
  `datariver-poc:e131550b7fa441de85ded5b7b55083d77b8c643e`;
- archive:
  `datariver-poc-e131550b7fa441de85ded5b7b55083d77b8c643e-linux-amd64.tar`;
- archive SHA-256:
  `db23213c21725227eb41f93688bde4276505877b80f34a94dca4e9d1adbd0962`;
- child manifest:
  `sha256:05a0dc45a3ad9b86f2c0d1790d5dd7bf4ae291eb2f7537ac7cda76653e71e266`;
- config digest:
  `sha256:3332a736f38f90084db0d1bad7043e73e9923e53cad205361945efd1c574f18a`;
- platform: `linux/amd64`;
- OCI revision:
  `e131550b7fa441de85ded5b7b55083d77b8c643e`.

The archive is an ignored release artifact. The Handoff pins these exact fields
in `deploy/prep39083/release.json`; deployment must retain `pull_policy: never`,
`--no-build`, and the existing fail-closed checksum/manifest/config/platform/
revision contract.

## Runtime boundary

- Existing TEST PC acceptance is preserved. The Wave B Product was not deployed
  because the approved TEST transport/browser session is unavailable; this is
  `BLOCKED_EXTERNAL`, not a local PASS.
- User DataHub metadata modified: NO.
- Actual PREP: NOT EXECUTED.
- Actual OPS: NOT EXECUTED.
- `origin/main`: unchanged and frozen.

Wave B is `LOCAL_VERIFIED` with `15/17` completed locally, two explicitly
bounded `NEEDS_DECISION` items, and TEST PC runtime/browser acceptance pending.
