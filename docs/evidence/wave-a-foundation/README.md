# Wave A foundation evidence

## Scope

This checkpoint records the first coherent wave of the continuous feature
program. The Product is
`5ab575ffa3a0f8dba7657245de182ae940fdb325`.

The Product delta is intentionally limited to:

- canonical PM/backlog and design-constraint documentation;
- Catalog detail close, focus restoration, transient route state and query
  preservation;
- bounded Cytoscape node geometry and valid design-token font weights;
- removal of runtime inline-style writes in the affected Catalog/graph path;
- removal of a small set of repeated developer-facing shell/page copy.

It does not change Product authorization, provider contracts, DataHub data,
K9/MCL behavior, migrations, deployment state, or release artifact policy.
AF-01 required no Product change: the pinned Airflow 3.3.0 image parsed all six
tracked DAGs without an import error. The reported authenticated Catalog-open
401 was not reproduced locally, so its final network/console acceptance remains
a TEST PC browser gate rather than a source PASS claim.

## Source verification

The Control Plane verified the exact Product candidate with:

- focused navigation, Catalog and graph component tests: `43/43` PASS;
- focused App/navigation/copy tests: `83/83` PASS;
- full UI suite: `90` files, `668/668` PASS;
- ESLint: PASS;
- TypeScript typecheck: PASS;
- application build: PASS;
- POC build: PASS;
- migration checksum integrity: `2/2` PASS;
- static/source contract: PASS;
- `git diff --check`: PASS.

The build emitted only the existing large-chunk advisory. The UI suite retained
its existing jsdom canvas and local-storage warnings while exiting successfully.
No browser or TEST PC result is inferred from these local gates.

An independent Antigravity Gemini 3.1 Pro High review found no blocker in the
exact OCI/archive contract. The Control Plane separately confirmed that the
exporter requires a clean exact Product checkout, an existing amd64 Product
image, its matching OCI revision and an OCI child manifest; it does not build,
pull or load an image.

## Exact Product artifact

The clean Product was built once for `linux/amd64` with OCI revision equal to
the Product SHA and exported without rebuilding:

- image reference:
  `datariver-poc:5ab575ffa3a0f8dba7657245de182ae940fdb325`;
- archive:
  `datariver-poc-5ab575ffa3a0f8dba7657245de182ae940fdb325-linux-amd64.tar`;
- archive SHA-256:
  `394097a313e0d63383be1c95ada13590bff206ed0944deb89e3c4d33b28591a6`;
- child manifest:
  `sha256:21796e46c34270fd4d3b70dc17bbbd990d3dbd5b2091a7f5fbaefdeba33d143f`;
- config digest:
  `sha256:c0eb5587cbac5e8741443cced60ad1386042d4996c937b845661dbf1da581dee`;
- platform: `linux/amd64`;
- runtime user: `node`;
- OCI revision:
  `5ab575ffa3a0f8dba7657245de182ae940fdb325`.

The archive remains ignored and outside Git. The Handoff must pin these exact
fields in `deploy/prep39083/release.json`. TEST deployment must load this
archive, keep `pull_policy: never`, start with `--no-build`, and fail closed on
any checksum, manifest, config, platform or revision mismatch.

## Runtime status

- Starting TEST acceptance: preserved; no reset or mutation was performed by
  this local checkpoint.
- Wave A TEST accepted-state redeploy: not yet executed at this Evidence
  checkpoint.
- Actual PREP: NOT EXECUTED.
- Actual OPS: NOT EXECUTED.
- `origin/main`: unchanged.

Wave A remains `LOCAL_VERIFIED` until the exact Handoff and archive pass the
existing accepted-state TEST PC redeploy, 6/6 smoke, and affected browser/network
console checks.
