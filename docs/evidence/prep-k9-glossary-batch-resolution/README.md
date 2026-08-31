# PREP K9 bounded GlossaryTerm batch-resolution evidence

Recorded: 2026-08-31 (Asia/Seoul)  
Product: `d9736e21d9bed5f44f11687ff39e3017c9836c7a`

## Preserved PREP state and exact root cause

The prior Product `6f2374fb37f1243f0eaba6c025b8d2fb4e0cbc40` passed the PostgreSQL
compatibility, already-V5 idempotency and catalog `contype::text` portability paths, then failed
closed at K9 metadata collection with `GLOSSARY_DIRECT_RESOLUTION_LIMIT_EXCEEDED`. Actual PREP
was not accessed and its PostgreSQL database, K9 graph/LKG, receipts, volumes and DataHub metadata
were not changed.

Direct resolution is the exact-URN recovery of unique GlossaryTerm assignment references present
on the current authorized Dataset/SchemaField inventory but absent from the complete glossary
scroll snapshot. It is not a Dataset, page, relationship-edge or authorization-filter count. The
old implementation imposed a hard-coded ceiling of 1,000 unique missing Term URNs and issued one
GraphQL `entity(urn)` request for each. PREP therefore proved at least 1,001 such unique references;
the exact total is not needed for a safe correction.

The correction removes that total-count assumption and reuses DataHub's existing verified
`entities(urns, checkForExistence: true)` contract in deterministic sorted batches of 250. Batches
run sequentially, response cardinality and positional URN identity are checked exactly, and
duplicate references remain deduplicated. Existing removed/non-current exclusion, exact identity,
authorization-derived inventory scope, K9 consistency fence, LKG protection, provider failure
classification and fail-closed behavior are unchanged. No timeout, glossary scope or total limit
was expanded and no DataHub mutation was added.

## Verification

- focused collector and source-contract tests: `36/36 PASS`;
- K9 collector/managed-graph/scheduler integration tests: `76/76 PASS`;
- boundary fixtures: `999`, `1,000`, `1,001` and `2,501` unique direct references;
- batch correctness: deterministic order, no omission, no duplication, maximum 250 URNs/request;
- removed, absent, wrong-type, malformed and positional identity mismatch paths remain fail-closed;
- full applicable POC Node suite: `248 tests / 232 PASS / 16 isolated PostgreSQL skips / 0 FAIL`;
- touched-file ESLint: PASS;
- `scripts/verify_static.py`: PASS.

The PostgreSQL paths were not reopened. The isolated skips require explicitly acknowledged real
PostgreSQL targets and do not affect this DataHub GraphQL-only correction.

## Exact build-once artifact

- image: `datariver-poc:d9736e21d9bed5f44f11687ff39e3017c9836c7a`
- platform: `linux/amd64`
- archive: `datariver-poc-d9736e21d9bed5f44f11687ff39e3017c9836c7a-linux-amd64.tar`
- archive size: `124297216` bytes
- archive SHA-256: `f5a7a49237bf42c355184fc5ae296c17ceee0606f9534f2194456d3b5ce73d3a`
- manifest: `sha256:4232039d3577ad02f15873f201d4802a5a0b75b301ba34ff988ca26c053caadf`
- config: `sha256:b8de513ef9f8a74091dde8a6f14e4e774b58ceb34a028a59684f185239774bad`
- OCI revision: `d9736e21d9bed5f44f11687ff39e3017c9836c7a`
- runtime command: `node poc-server.mjs`
- required Node runtime files and non-root runtime preflight: PASS

The canonical artifact script built this archive from a separate clean exact `dev` clone. The
first canonical invocation ended after a transient linux/amd64 build-process segmentation fault
and produced no archive; the unchanged canonical command then completed. No previous artifact,
manual Dockerfile, frontend-only image or target-side build was used. Actual PREP doctor, deploy
and rerun remain **NOT EXECUTED** by the Control Plane. Reset/resecret and user metadata mutation
remain NONE. `origin/main` remains unchanged at
`17f32a52de79077c433bf0beaabac81a48e46062`.
